"""Configuracao do Celery.

O worker e o servico que justifica o HorizontalPodAutoscaler do projeto: a
carga de sincronizacao e irregular por natureza — quase nula em repouso, alta
quando varios usuarios sincronizam ao mesmo tempo. Escalar por tamanho de fila
e uma resposta a uma variacao real, nao autoescalamento decorativo.

Decisoes que valem explicacao:

**Pool de threads, nao de processos.** O trabalho aqui e de entrada e saida —
esperar a API externa e esperar o banco —, nao de CPU. Threads bastam, e tem
uma vantagem concreta: todas as tarefas rodam no mesmo processo, entao o
contador do Prometheus e unico e o `/metrics` reporta o total correto. Com o
pool `prefork`, cada processo filho teria o seu proprio contador e a metrica
viria pela metade.

**`acks_late`.** A tarefa so e confirmada depois de concluida. Se o pod morrer
no meio da sincronizacao, a mensagem volta para a fila e outro worker refaz.
O preco e a tarefa poder executar duas vezes — por isso ela e idempotente.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready
from prometheus_client import start_http_server

from prismo_shared import configure_logging, get_settings

settings = get_settings()

app = Celery("prismo", broker=settings.broker, backend=settings.backend)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Entrega tardia: ver explicacao no docstring.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Uma tarefa por vez em memoria, por worker. Sem isto, um worker reserva
    # um lote grande de mensagens e os demais ficam ociosos — o que faria o
    # HPA escalar sem ganho nenhum.
    worker_prefetch_multiplier=1,
    # Teto de tempo: uma sincronizacao presa nao pode segurar a fila para
    # sempre. O soft dispara excecao tratavel; o hard mata a tarefa.
    task_soft_time_limit=240,
    task_time_limit=300,
    result_expires=3600,
    # Descarta resultado de tarefa que ninguem consulta, evitando encher o
    # Redis com retorno que nao sera lido.
    task_ignore_result=False,
)

# Agenda do Beat: e isto que torna o portfolio "auto-atualizavel", que e o
# pedido central do projeto 14.
app.conf.beat_schedule = {
    "sincronizar-todas-as-conexoes": {
        "task": "prismo.sincronizar_todas",
        "schedule": crontab(minute=f"*/{settings.sync_intervalo_minutos}"),
    },
    # A recencia do score decai com o tempo: um ranking correto hoje estara
    # errado em um mes sem nada ter mudado. Recalcular de madrugada mantem a
    # ordenacao fiel sem concorrer com o uso.
    "recalcular-scores": {
        "task": "prismo.recalcular_scores",
        "schedule": crontab(hour="4", minute="30"),
    },
}

# Importa o modulo das tarefas para que o Celery as registre.
app.autodiscover_tasks(["app"], related_name="tarefas", force=True)


@worker_ready.connect
def publicar_metricas(**_kwargs) -> None:
    """Sobe um servidor HTTP minimo em :8000/metrics quando o worker fica pronto.

    O Celery nao expoe metricas sozinho, e o Prometheus so sabe raspar HTTP.
    O `start_http_server` do prometheus_client resolve isso com um servidor de
    uma rota, sem trazer FastAPI para dentro do worker.

    Ligado a `worker_ready` e nao ao import do modulo porque o Beat usa este
    mesmo arquivo: sem o sinal, os dois tentariam ocupar a mesma porta.
    """
    configure_logging("worker", settings.log_level)
    start_http_server(8000)

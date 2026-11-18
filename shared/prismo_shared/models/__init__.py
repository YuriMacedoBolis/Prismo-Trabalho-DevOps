"""Modelos de dados do Prismo.

**Um banco, um schema por dominio.** Os servicos compartilham a instancia do
Postgres, mas cada dominio vive no seu proprio schema: `auth` para contas,
`portfolio` para conteudo. Nenhum servico le ou escreve tabela de schema que
nao e seu.

Por que nao um banco por servico, que seria o livro-texto: para a escala deste
projeto, sete bancos significariam sete backups, sete pools e nenhuma consulta
entre dominios — custo operacional alto para um ganho que so aparece quando
equipes diferentes evoluem servicos em ritmos diferentes. O schema separado
mantem a fronteira visivel e deixa a separacao fisica como passo futuro, sem
reescrever nada: basta apontar o `DATABASE_URL` de um servico para outro host.

Por que os modelos ficam na biblioteca compartilhada: o migrator precisa
enxergar todas as tabelas para gerar uma migration unica e consistente. Com os
modelos espalhados pelos servicos, cada um teria o seu historico do Alembic e a
ordem de aplicacao entre eles viraria problema.

**A fronteira que respeitamos:** nao existe chave estrangeira cruzando schema.
`portfolio.portfolios.usuario_id` guarda o id do usuario, mas sem FK para
`auth.usuarios`. Uma FK ali amarraria os dois dominios no nivel do banco e
impediria separa-los depois.
"""

from .base import Base, metadata
from .auth import Usuario
from .portfolio import Conexao, Plataforma, Portfolio, Projeto, Sincronizacao, StatusSync

__all__ = [
    "Base",
    "Conexao",
    "Plataforma",
    "Portfolio",
    "Projeto",
    "Sincronizacao",
    "StatusSync",
    "Usuario",
    "metadata",
]

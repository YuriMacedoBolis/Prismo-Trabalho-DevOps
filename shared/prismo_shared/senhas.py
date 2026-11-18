"""Hash de senha com Argon2id.

Modulo separado de `security.py` de proposito. O Argon2 vem de
`requirements-db.txt`, instalado apenas nos servicos que lidam com contas; o
gateway valida token mas nunca ve senha, e nao deve carregar essa dependencia.
Juntar as duas coisas no mesmo modulo obrigaria todo servico que valida JWT a
instalar Argon2 tambem.

**Argon2id, nao SHA-256.** Hash de proposito geral e rapido, e rapidez e
exatamente o que o atacante quer: uma GPU testa bilhoes de SHA-256 por
segundo. Argon2id e deliberadamente lento e consome memoria, o que torna a
forca bruta cara mesmo com hardware dedicado. Venceu a Password Hashing
Competition e e a recomendacao atual da OWASP.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Parametros padrao da biblioteca, alinhados a recomendacao da OWASP
# (19 MiB de memoria, 2 iteracoes, 1 thread).
_hasher = PasswordHasher()


def gerar_hash_senha(senha: str) -> str:
    return _hasher.hash(senha)


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    try:
        _hasher.verify(hash_armazenado, senha)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def precisa_rehash(hash_armazenado: str) -> bool:
    """True quando o hash foi gerado com parametros mais fracos que os atuais.

    Permite fortalecer as senhas gradualmente: no proximo login bem-sucedido o
    hash e regravado com os parametros novos, sem pedir nada ao usuario.
    """
    try:
        return _hasher.check_needs_rehash(hash_armazenado)
    except InvalidHashError:
        return True

# -*- coding: utf-8 -*-
"""
Configuração do gunicorn — existe por uma razão só: o log de acesso.

O CMD roda com `--access-logfile -`, e é isso que se quer: no EasyPanel o log do
container é como se enxerga o que o sistema está fazendo. Mas o log registra o
CAMINHO da requisição, e o caminho de `/recuperar/<token>` CARREGA O TOKEN — a
coisa que dá acesso à conta de alguém sem pedir a senha. Em texto no log, ele é
legível pelo painel do provedor e por qualquer backup dele, durante os 30 minutos
em que vale.

O ÁTOMO CERTO É `r`, NÃO `U` — e errar isso é escrever uma proteção que não
protege. O formato PADRÃO do gunicorn é

    %(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"

e ele NÃO usa `%(U)s`. Quem imprime o caminho ali é `%(r)s`, montado do RAW_URI
como "GET /recuperar/<token> HTTP/1.1". Uma primeira versão desta classe reescrevia
só `U`, passava no teste que olhava `U`, e deixava o token intacto no log. Os dois
átomos são reescritos aqui, e o teste confere a LINHA FORMATADA — não o átomo.

A regra de quais caminhos carregam segredo mora em `seguranca.caminho_sem_segredo`,
porque o servidor de desenvolvimento tem o mesmo problema com outro dono, e porque
o `gunicorn` não instala no Windows: deixá-la aqui a tornaria impossível de testar
na máquina onde o projeto é desenvolvido.

Uso: `gunicorn -c gunicorn_conf.py ...` (o Dockerfile já passa).
"""
from gunicorn import glogging

import seguranca as seg


class Logger(glogging.Logger):
    """Igual ao padrão, menos o segredo."""

    def atoms(self, resp, req, environ, request_time):
        return seg.atomos_sem_segredo(
            super().atoms(resp, req, environ, request_time))


logger_class = Logger

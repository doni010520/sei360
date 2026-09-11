# -*- coding: utf-8 -*-
"""
As portas do sistema, em UMA lista.

Por que isto existe: a mesma navegação era escrita em dois lugares — a barra das
telas de serviço e o menu de conta do painel. Duas listas divergem: "Pessoas"
existia só como URL que alguém precisava saber de cor, e "Alertas" apareceu numa
sem aparecer na outra. Uma lista, N renderizações.

`papeis=None` quer dizer "todo mundo que entrou". A regra de papel mora AQUI e é
lida pela navegação E pela rota — quando as duas leem coisas diferentes, some o
item do menu e a URL continua servindo.

O SUBTÍTULO não é enfeite. "Configuração" sozinho não diz se é do sistema, da
conta ou da coleta; "Login e horários da coleta" diz. Numa carteira que se abre
uma vez por dia, ler o rótulo e ainda ter de adivinhar custa um clique errado
por visita.
"""

# Ícones em traço, 24x24, herdando a cor — desenhados no mesmo vocabulário do
# painel de leitos do HECC (lucide, ISC). Sem biblioteca: são quatro traços cada.
_ICONES = {
    "painel": '<rect width="7" height="9" x="3" y="3" rx="1"/>'
              '<rect width="7" height="5" x="14" y="3" rx="1"/>'
              '<rect width="7" height="9" x="14" y="12" rx="1"/>'
              '<rect width="7" height="5" x="3" y="16" rx="1"/>',
    # lupa: o mesmo traço do ícone de busca do painel
    "busca": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    # marcador de página — a mesma família de traço dos outros, sem `<svg>` em
    # volta (quem desenha a moldura é `_nav.html`, com um `<svg>` só).
    "acompanhamento": '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    "relatorios": '<path d="M3 3v18h18"/><path d="M18 17V9"/>'
                  '<path d="M13 17V5"/><path d="M8 17v-3"/>',
    "alertas": '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 '
               '3.86a2 2 0 0 0-3.42 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "usuarios": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
                '<circle cx="9" cy="7" r="4"/>'
                '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "configuracao": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l'
                    '.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 '
                    '0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33'
                    'l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 '
                    '0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82'
                    'l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 '
                    '0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33'
                    'l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 '
                    '0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>',
    "admin": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 '
             '0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 '
             '1 1 1z"/>',
}

PORTAS = [
    # O painel É uma porta do menu, e a primeira. Ele é a tela inicial e a mais
    # usada — e era justamente a única sem navegação nenhuma.
    {"id": "painel", "rotulo": "Controle de Processos",
     "subtitulo": "Triagem da carteira", "url": "/", "papeis": None},
    # A busca vem logo depois do painel porque é a segunda pergunta de quem abre
    # o sistema: "e o processo que NÃO está na minha carteira?". A carteira é o
    # que chegou até a mesa; a busca é o resto do SEI, com o login de quem pergunta.
    {"id": "busca", "rotulo": "Busca avançada",
     "subtitulo": "Pesquisar no SEI com o seu login", "url": "/busca", "papeis": None},
    # Terceira pergunta de quem abre o sistema, depois de "o que chegou na minha
    # mesa?" (painel) e "e o que NÃO chegou?" (busca): "e aquele processo que eu
    # não quero perder de vista, onde ele foi parar?". A carteira responde
    # enquanto o processo está na mesa; quando ele sai, o painel fica cego — e é
    # exatamente aí que alguém mais precisa de resposta.
    {"id": "acompanhamento", "rotulo": "Acompanhamento",
     "subtitulo": "Processos que você segue, onde estiverem",
     "url": "/acompanhamento", "papeis": None},
    {"id": "relatorios", "rotulo": "Relatórios",
     "subtitulo": "Números com procedência", "url": "/relatorios", "papeis": None},
    {"id": "alertas", "rotulo": "Alertas",
     "subtitulo": "O que precisa de decisão", "url": "/alertas",
     "papeis": ("gestor", "admin")},
    # Pessoas existia como tela, mas só quem soubesse a URL `/admin/usuarios`
    # chegava nela — e ela é onde se descobre por que fulano "não vê nada", que
    # é a dúvida mais comum do suporte.
    {"id": "usuarios", "rotulo": "Pessoas",
     "subtitulo": "Quem acessa e o que vê", "url": "/admin/usuarios",
     "papeis": ("gestor", "admin")},
    {"id": "configuracao", "rotulo": "Configuração",
     "subtitulo": "Login e horários da coleta", "url": "/configuracao", "papeis": None},
    {"id": "admin", "rotulo": "Administração",
     "subtitulo": "Agentes, IA e expurgo", "url": "/admin", "papeis": ("admin",)},
]

for _p in PORTAS:
    _p["icone"] = _ICONES[_p["id"]]

MARCA = {"titulo": "SEI360", "subtitulo": "Carteira SESAB"}


def pode(porta, papel):
    return not porta["papeis"] or papel in porta["papeis"]


def visiveis(papel):
    return [p for p in PORTAS if pode(p, papel)]


def por_id(pid):
    return next((p for p in PORTAS if p["id"] == pid), None)

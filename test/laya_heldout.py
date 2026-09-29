"""Held-out routing cases for Laya — written 2026-09-29, BEFORE any of the
improvements they are used to judge, and not edited after seeing results.

The original 24 (laya-eval.py) are now a development set: their misses have
been read, so anything tuned while looking at them has to prove itself here.
These are phrased differently on purpose — terse, indirect, with typos and
Spanish, the way people actually type into a shell.
"""

HELDOUT = [
    ("linkedin post pls, we hit 1000 customers", "app/social-media"),
    ("necesito un tuit sobre el webinar del jueves", "app/social-media"),
    ("reply to the comments under yesterday's post", "app/social-media"),
    ("what should we post this week", "app/social-media"),
    ("anything interesting in the news about RISC-V?", "app/article-scout"),
    ("busca artículos sobre inferencia en el edge", "app/article-scout"),
    ("is this hacker news thread worth sharing", "app/article-scout"),
    ("find me 5 good reads on AI regulation", "app/article-scout"),
    ("typo on the careers page, 'recieve'", "app/web-content"),
    ("the website still lists the old CEO", "app/web-content"),
    ("cambia el texto de la portada", "app/web-content"),
    ("does our site claim SOC2? we don't have it yet", "app/web-content"),
    ("what's initech charging now", "app/competitors"),
    ("did anyone launch something like our shell agent", "app/competitors"),
    ("compare our features with the top 3 alternatives", "app/competitors"),
    ("qué ha sacado la competencia este mes", "app/competitors"),
    ("TAM for AI appliances in LATAM?", "app/market"),
    ("is the SMB segment worth it", "app/market"),
    ("tamaño del mercado de inferencia local en España", "app/market"),
    ("which industries are buying on-prem AI", "app/market"),
    ("where's the NDA we signed with Hooli", "app/librarian"),
    ("I need the Q2 board minutes", "app/librarian"),
    ("dónde está la política de vacaciones", "app/librarian"),
    ("who has access to the finance folder", "app/librarian"),
]

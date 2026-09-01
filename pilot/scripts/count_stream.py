#!/usr/bin/env python3
import sys
from collections import Counter
import chess.pgn

def band(r):
    r = int(r)
    if r < 1000:
        return '<1000'
    if r < 1500:
        return '1000-1499'
    if r < 2000:
        return '1500-1999'
    if r < 2300:
        return '2000-2299'
    return '2300+'

c = Counter()
n = 0
while True:
    g = chess.pgn.read_game(sys.stdin)
    if g is None:
        break
    n += 1
    if n % 5000 == 0:
        print(f"processed={n}", file=sys.stderr, flush=True)
    if g.headers.get('TimeControl') != '300+0':
        continue
    we = g.headers.get('WhiteElo')
    be = g.headers.get('BlackElo')
    if not we or not be:
        continue
    wb = band(we)
    bb = band(be)
    if wb == bb:
        c[wb] += 1
print('games', n)
print(dict(c))

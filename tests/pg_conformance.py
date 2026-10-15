#!/usr/bin/env python3
"""PostgreSQL 18 conformance check for the formatter.

Formats every statement of two corpora built from the official PostgreSQL 18
documentation and checks that formatting never changes the SQL:

- tests/pg18/doc_examples.json: SQL code blocks extracted from the PDF manual
  (examples in the reference pages and in the chapters);
- tests/pg18/synopsis_*.sql: statements written to cover every form in the
  Synopsis of all SQL command reference pages (tests/pg18/synopsis.json is the
  same corpus pre-split, used when pglast is not installed).

Each JSON item records `valid`: whether PostgreSQL 18's parser accepted it when the
corpus was built (re-checked live when pglast is available).

Checks per statement: no exception, not left verbatim/raw, same significant tokens,
comments kept, idempotent. With `pglast` (PostgreSQL's own parser, v8 = PG 18)
installed, also: input and output parse to the same tree. Statements PostgreSQL
rejects (pseudo-code in the manual) are only checked for token/comment safety.

Usage: python3 tests/pg_conformance.py [--show CATEGORY] [--limit N] [--regress DIR]
pglast is optional and only used here:  pip install pglast   (e.g. in a venv)

--regress DIR runs the same checks over PostgreSQL's own regression-test SQL instead,
i.e. src/test/regress/sql of a PostgreSQL 18 source tree (~48,700 statements written to
exercise every feature). psql meta-command lines and COPY ... FROM stdin data are
skipped; files PostgreSQL's scanner can't split (deliberately invalid lexemes) are split
with the formatter's own statement boundaries.
"""

import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pgfmt  # noqa: E402
from pgfmt.formatter import ASTFormatter  # noqa: E402
from pgfmt.formatter.base import _significant_tokens  # noqa: E402
from pgfmt.parser import Parser  # noqa: E402
from pgfmt.tokenizer import tokenize  # noqa: E402

try:
    from pglast import parser as pgparser, split as pgsplit
except ImportError:
    pgparser = pgsplit = None


def pg_tree(sql):
    """PostgreSQL's parse tree without source positions, or None if it doesn't parse."""
    try:
        tree = json.loads(pgparser.parse_sql_json(sql))
    except Exception:
        return None

    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items()
                    if not (k.endswith('location') or k.endswith('list_start')
                            or k.endswith('list_end') or k == 'stmt_len')}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    return strip(tree)


def comments(sql):
    return collections.Counter(t[1].rstrip() for t in tokenize(sql) if t[0] == 'COMMENT')


def load_regress(path):
    """Statements of PostgreSQL's regression-test SQL files (needs pglast to split them)."""
    import re
    if pgsplit is None:
        sys.exit('--regress needs pglast (pip install pglast)')
    items = []
    for f in sorted(glob.glob(os.path.join(path, '*.sql'))):
        text = open(f, encoding='utf-8', errors='replace').read()
        text = re.sub(r'(?ims)^(copy\b[^;]*\bfrom\s+stdin[^;]*;)\n.*?^\\\.\s*$', r'\1', text)
        text = '\n'.join(ln for ln in text.split('\n') if not ln.lstrip().startswith('\\'))
        try:
            stmts = pgsplit(text, with_parser=False)
        except Exception:
            spans = []
            stmts = [getattr(r, '_src_text', '') for r in Parser(tokenize(text, spans), text, spans).parse_all()
                     if type(r).__name__ != 'CommentGroup']
            stmts = [s[:-1] if s.endswith(';') else s for s in stmts]
        for k, s in enumerate(stmts):
            if s.strip():
                items.append({'line': k + 1, 'section': os.path.basename(f), 'sql': s.strip() + ';',
                              'corpus': 'regress'})
    return items


def load_corpora():
    items = [dict(x, corpus='docs') for x in json.load(open(os.path.join(HERE, 'pg18', 'doc_examples.json')))]
    if pgsplit is not None:
        for f in sorted(glob.glob(os.path.join(HERE, 'pg18', 'synopsis_*.sql'))):
            for k, stmt in enumerate(pgsplit(open(f).read(), with_parser=True)):
                items.append({'line': k + 1, 'section': os.path.basename(f), 'sql': stmt.strip() + ';',
                              'corpus': 'synopsis', 'valid': True})
    else:
        items += [dict(x, corpus='synopsis') for x in json.load(open(os.path.join(HERE, 'pg18', 'synopsis.json')))]
    return items


def check(sql):
    """Problems found formatting one statement (empty list = ok), and the output."""
    spans = []
    try:
        res = Parser(tokenize(sql, spans), sql, spans).parse_all()
        out = ASTFormatter().format_all(res)
    except Exception as e:  # pragma: no cover - reported, never expected
        return ['exception: ' + repr(e)], ''
    probs = []
    kinds = {type(r).__name__ for r in res}
    if 'VerbatimStatement' in kinds:
        probs.append('verbatim')
    if 'RawStatement' in kinds:
        probs.append('raw')
    if _significant_tokens(out) != _significant_tokens(sql):
        probs.append('tokens')
    if comments(sql) - comments(out):
        probs.append('comments')
    if pgfmt.format_sql(out) != out:
        probs.append('idempotency')
    return probs, out


def main():
    args = sys.argv[1:]
    show = args[args.index('--show') + 1] if '--show' in args else None
    limit = int(args[args.index('--limit') + 1]) if '--limit' in args else 10
    items = load_regress(args[args.index('--regress') + 1]) if '--regress' in args else load_corpora()
    cats = collections.defaultdict(list)
    valid = 0
    for it in items:
        sql = it['sql']
        tree = pg_tree(sql) if pgparser else None
        # without pglast, fall back to the validity recorded when the corpus was built
        is_sql = tree is not None if pgparser else it.get('valid', True)
        probs, out = check(sql)
        if not is_sql:
            # not runnable SQL (manual pseudo-code / prose): only content safety matters
            probs = [p for p in probs if p in ('tokens', 'comments', 'idempotency') or p.startswith('exception')]
        if pgparser and is_sql:
            valid += 1
            after = pg_tree(out)
            if after is None:
                probs.append('invalid_output')
            elif after != tree:
                probs.append('semantic')
        for p in probs or ['ok']:
            cats[p.split(':')[0]].append((it, out))
    print(f'{len(items)} statements' + (f' ({valid} valid PostgreSQL 18, checked against its parse tree)'
                                        if pgparser else ' (pglast not installed: no parse-tree check)'))
    order = ['ok', 'exception', 'invalid_output', 'semantic', 'tokens', 'comments', 'idempotency', 'verbatim', 'raw']
    for k in order:
        print(f'  {k:15} {len(cats[k])}')
    if show:
        for it, out in cats[show][:limit]:
            print('=' * 80)
            print(f"[{it['corpus']}] {it['section']} line {it['line']}")
            print(it['sql'])
            print('-' * 40)
            print(out)
    bad = sum(len(v) for k, v in cats.items() if k != 'ok')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()

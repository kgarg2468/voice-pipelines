#!/usr/bin/env python3
"""sync_neo4j — build the Company Brain conflict graph in Neo4j.

The graph is the structured, queryable twin of the Obsidian vault. It's rebuilt
deterministically from two sources:
  - GitHub (via `gh`): issues (all states) and PRs (with changed files + labels).
  - Live presence: vault/presence/<person>.md (what each agent is editing right now).

Model:
  (:Person)-[:AUTHORED]->(:PR)        (:PR)-[:ABOUT]->(:Feature)   (:PR)-[:CLOSES]->(:Issue)
  (:PR)-[:TOUCHES]->(:File)           (:File)-[:PART_OF]->(:Feature)
  (:Issue)-[:ABOUT]->(:Feature)       (:Person)-[:INTERESTED_IN]->(:Issue)
  (:Person)-[:WORKING_ON {kind:'live'|'pushed'}]->(:Feature)   ← the conflict edge

  python3 sync_neo4j.py            # rebuild the graph + print the conflict summary
"""
import json, os, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import companybrain as cb  # feature_of, PRESENCE, DEFAULT_REPO, load_env

NEO4J_URI = os.environ.get("COMPANYBRAIN_NEO4J_URI") or os.environ.get("ROCKETRIDE_NEO4J_URI") or "neo4j://localhost:7687"
NEO4J_USER = os.environ.get("COMPANYBRAIN_NEO4J_USER") or os.environ.get("ROCKETRIDE_NEO4J_USER") or "neo4j"
NEO4J_PASSWORD = os.environ.get("COMPANYBRAIN_NEO4J_PASSWORD") or os.environ.get("ROCKETRIDE_NEO4J_PASSWORD") or "companybrain"


def _driver():
    from neo4j import GraphDatabase
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def _gh_json(args):
    out = subprocess.run([cb.gh_bin()] + args, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "gh failed")
    return json.loads(out.stdout or "[]")


def _labels(item):
    persons, feats = [], []
    for lab in item.get("labels", []):
        name = lab.get("name", "") if isinstance(lab, dict) else str(lab)
        if name.startswith("person:"):
            persons.append(name.split(":", 1)[1])
        elif name.startswith("feature:"):
            feats.append(name.split(":", 1)[1])
    return persons, feats


def _read_presence():
    """[(person, working_on, [files])] from vault/presence/*.md."""
    out = []
    if not cb.PRESENCE.is_dir():
        return out
    for md in sorted(cb.PRESENCE.glob("*.md")):
        person, working_on, files = md.stem, "", []
        for line in md.read_text().splitlines():
            wm = re.match(r"working_on:\s*(.+)$", line)
            fm = re.match(r"\s*-\s+`([^`]+)`", line)
            if wm:
                working_on = wm.group(1).strip()
            elif fm:
                files.append(fm.group(1))
        out.append((person, working_on, files))
    return out


def sync(repo=None):
    """Rebuild the whole graph (small + deterministic). Returns counts."""
    repo = repo or os.environ.get("ROCKETRIDE_GITHUB_REPO") or cb.DEFAULT_REPO
    issues = _gh_json(["issue", "list", "--repo", repo, "--state", "all",
                       "--json", "number,title,state,labels", "--limit", "100"])
    prs = _gh_json(["pr", "list", "--repo", repo, "--state", "all",
                    "--json", "number,title,state,isDraft,labels,files", "--limit", "100"])
    presence = _read_presence()

    drv = _driver()
    with drv.session() as s:
        s.run("MATCH (n) DETACH DELETE n")  # full rebuild — the graph is tiny

        for iss in issues:
            persons, feats = _labels(iss)
            state = (iss.get("state") or "open").lower()
            s.run("MERGE (i:Issue {number:$n}) SET i.title=$t, i.state=$st",
                  n=iss["number"], t=iss["title"], st=state)
            for f in feats:
                s.run("MERGE (ft:Feature {slug:$f}) MERGE (i:Issue {number:$n}) MERGE (i)-[:ABOUT]->(ft)",
                      f=f, n=iss["number"])
            for p in persons:
                s.run("MERGE (pe:Person {name:$p}) MERGE (i:Issue {number:$n}) MERGE (pe)-[:INTERESTED_IN]->(i)",
                      p=p, n=iss["number"])

        for pr in prs:
            persons, feats = _labels(pr)
            raw = (pr.get("state") or "OPEN").lower()
            state = "draft" if pr.get("isDraft") else raw  # open|draft|merged|closed
            in_flight = state in ("open", "draft")
            s.run("MERGE (pr:PR {number:$n}) SET pr.title=$t, pr.state=$st", n=pr["number"], t=pr["title"], st=state)
            files = [f.get("path") for f in pr.get("files", []) if f.get("path")]
            for path in files:
                s.run("MERGE (fl:File {path:$p}) MERGE (pr:PR {number:$n}) MERGE (pr)-[:TOUCHES]->(fl)",
                      p=path, n=pr["number"])
                feat = cb.feature_of(path)
                if feat:
                    s.run("MERGE (ft:Feature {slug:$f}) MERGE (fl:File {path:$p}) MERGE (fl)-[:PART_OF]->(ft)",
                          f=feat, p=path)
            file_feats = {cb.feature_of(p) for p in files if cb.feature_of(p)}
            for f in (set(feats) | file_feats):
                s.run("MERGE (ft:Feature {slug:$f}) MERGE (pr:PR {number:$n}) MERGE (pr)-[:ABOUT]->(ft)",
                      f=f, n=pr["number"])
            for p in persons:
                s.run("MERGE (pe:Person {name:$p}) MERGE (pr:PR {number:$n}) MERGE (pe)-[:AUTHORED]->(pr)",
                      p=p, n=pr["number"])
                if in_flight:  # open/draft PR ⇒ this person is actively working the feature(s)
                    for f in (set(feats) | file_feats):
                        s.run("MERGE (pe:Person {name:$p}) MERGE (ft:Feature {slug:$f}) "
                              "MERGE (pe)-[w:WORKING_ON {kind:'pushed'}]->(ft) SET w.pr=$n", p=p, f=f, n=pr["number"])

        for person, working_on, files in presence:
            feats = set()
            if working_on and cb.feature_of(working_on) == "" and not working_on.startswith("src/"):
                feats.add(working_on)  # working_on is already a feature slug
            feats |= {cb.feature_of(f) for f in files if cb.feature_of(f)}
            feats |= {cb.feature_of(working_on)} if cb.feature_of(working_on) else set()
            feats = {f for f in feats if f}
            for f in feats:
                s.run("MERGE (pe:Person {name:$p}) MERGE (ft:Feature {slug:$f}) "
                      "MERGE (pe)-[:WORKING_ON {kind:'live'}]->(ft)", p=person, f=f)
            for path in files:  # keep file-level edges for the visual
                s.run("MERGE (pe:Person {name:$p}) MERGE (fl:File {path:$f}) MERGE (pe)-[:EDITING]->(fl)",
                      p=person, f=path)

        counts = s.run("MATCH (n) WITH labels(n)[0] AS l, count(*) AS c RETURN collect([l,c]) AS x").single()["x"]
    drv.close()
    return dict(counts)


def conflict_summary():
    """Deterministic read: who is on what, which open issues are safe vs conflicting.
    This is also the query you run live in Neo4j Browser on stage."""
    drv = _driver()
    with drv.session() as s:
        active = [f"{r['p']} → {r['feat']} ({r['kind']})" for r in s.run(
            "MATCH (p:Person)-[w:WORKING_ON]->(f:Feature) "
            "RETURN p.name AS p, f.slug AS feat, w.kind AS kind ORDER BY feat, p")]
        hot = set(s.run("MATCH (:Person)-[:WORKING_ON]->(f:Feature) RETURN collect(DISTINCT f.slug) AS h").single()["h"])
        rows = list(s.run(
            "MATCH (i:Issue {state:'open'}) OPTIONAL MATCH (i)-[:ABOUT]->(f:Feature) "
            "RETURN i.number AS num, i.title AS title, f.slug AS feat ORDER BY num"))
    drv.close()
    safe, conflicting = [], []
    for r in rows:
        line = f"#{r['num']} {r['title']} [{r['feat'] or '?'}]"
        (conflicting if r["feat"] in hot else safe).append(line)
    parts = ["ACTIVE WORK (someone is on these features):"]
    parts += [f"  - {a}" for a in active] or ["  - (nobody is actively working anything)"]
    parts += ["", f"HOT FEATURES (avoid — would conflict): {', '.join(sorted(hot)) or '(none)'}"]
    parts += ["", "OPEN ISSUES IN UNTOUCHED AREAS (safe to pick up):"]
    parts += [f"  - {x}" for x in safe] or ["  - (none — everything open is being worked)"]
    parts += ["", "OPEN ISSUES THAT WOULD CONFLICT (someone is already on the feature):"]
    parts += [f"  - {x}" for x in conflicting] or ["  - (none)"]
    return "\n".join(parts)


def _yaml(s):
    """YAML-safe scalar (handles colons/quotes in titles)."""
    return json.dumps(s or "")


def build_vault(repo=None):
    """Deterministically (re)write the Obsidian vault from GitHub + presence — so the
    vault stays dense and 1:1 with the Neo4j graph even when the repo gets big. Presence
    notes are written by companybrain.log_activity and are left untouched here."""
    repo = repo or os.environ.get("ROCKETRIDE_GITHUB_REPO") or cb.DEFAULT_REPO
    issues = _gh_json(["issue", "list", "--repo", repo, "--state", "all",
                       "--json", "number,title,state,labels,body,url", "--limit", "200"])
    prs = _gh_json(["pr", "list", "--repo", repo, "--state", "all",
                    "--json", "number,title,state,isDraft,labels,files,body,url", "--limit", "200"])
    V = cb.VAULT
    people, feats = {}, {}

    def add(reg, key, kind, num):
        reg.setdefault(key, {"prs": set(), "issues": set()})[kind].add(num)

    for sub in ("issues", "prs", "people", "features"):  # rebuild these; keep presence/
        d = V / sub
        if d.is_dir():
            for old in d.glob("*.md"):
                old.unlink()
        d.mkdir(parents=True, exist_ok=True)

    for iss in issues:
        persons, fts = _labels(iss)
        n, st = iss["number"], (iss.get("state") or "open").lower()
        for p in persons:
            add(people, p, "issues", n)
        for f in fts:
            add(feats, f, "issues", n)
        links = [f"[[people/{p}]]" for p in persons] + [f"[[features/{f}]]" for f in fts]
        fm = ["---", "type: issue", f"number: {n}", f"title: {_yaml(iss['title'])}",
              f"state: {st}", f"url: {iss.get('url','')}", "---"]
        body = (iss.get("body") or "").strip().replace("\r", "")[:400]
        (V / "issues" / f"issue-{n}.md").write_text("\n".join(fm) + f"\n\n{body}\n\n" + " ".join(links) + "\n")

    for pr in prs:
        persons, fts = _labels(pr)
        n = pr["number"]
        raw = (pr.get("state") or "open").lower()
        st = "draft" if pr.get("isDraft") else raw
        files = [f.get("path") for f in pr.get("files", []) if f.get("path")]
        ffeats = {x for x in (set(fts) | {cb.feature_of(p) for p in files}) if x}
        body = (pr.get("body") or "").strip()
        closes = sorted({int(x) for x in re.findall(r"[Cc]loses #(\d+)", body)})
        for p in persons:
            add(people, p, "prs", n)
        for f in ffeats:
            add(feats, f, "prs", n)
        links = ([f"[[people/{p}]]" for p in persons] + [f"[[features/{f}]]" for f in sorted(ffeats)]
                 + [f"[[issues/issue-{c}]]" for c in closes])
        fm = ["---", "type: pr", f"number: {n}", f"title: {_yaml(pr['title'])}",
              f"state: {st}", f"url: {pr.get('url','')}"]
        if st in ("open", "draft"):
            fm += ["in_flight: true", "files:"] + [f"  - {p}" for p in files]
        fm += ["---"]
        (V / "prs" / f"pr-{n}.md").write_text("\n".join(fm) + f"\n\n{body[:400]}\n\n" + " ".join(links) + "\n")

    for name, info in sorted(people.items()):
        links = [f"[[prs/pr-{x}]]" for x in sorted(info["prs"])] + [f"[[issues/issue-{x}]]" for x in sorted(info["issues"])]
        fm = ["---", "type: person", f"name: {name}", "role: engineer", "---"]
        blurb = f"**{name}** — engineer. Active across {len(info['prs'])} PRs and {len(info['issues'])} issues."
        (V / "people" / f"{name}.md").write_text("\n".join(fm) + f"\n\n{blurb}\n\n" + " ".join(links) + "\n")

    for slug, info in sorted(feats.items()):
        links = [f"[[prs/pr-{x}]]" for x in sorted(info["prs"])] + [f"[[issues/issue-{x}]]" for x in sorted(info["issues"])]
        fm = ["---", "type: feature", f"slug: {slug}", "---"]
        (V / "features" / f"{slug}.md").write_text("\n".join(fm) + f"\n\n**{slug}** feature.\n\n" + " ".join(links) + "\n")

    return {"issues": len(issues), "prs": len(prs), "people": len(people), "features": len(feats)}


if __name__ == "__main__":
    cb.load_env()
    print("[sync] rebuilding graph + vault from GitHub + presence…", file=sys.stderr)
    counts = sync()
    vcounts = build_vault()
    print(f"[sync] graph nodes: {counts}", file=sys.stderr)
    print(f"[sync] vault notes: {vcounts}", file=sys.stderr)
    print(conflict_summary())

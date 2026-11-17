"""Turn scan results into JSON and a self-contained HTML report."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from .deps import GROUPS, KINDS

LABEL = {"ready": "Ready", "verify": "Verify", "wait": "Wait"}
COLOR = {"ready": "#4ADE9B", "verify": "#F5C04A", "wait": "#FF8A80"}
PRO_NOTE = ("Sovlens Pro lists every affected resource with a fix, and adds resource policies, "
            "S3 replication, network links, Lambda layers and infrastructure-as-code checks: https://sovlens.dev")


def build(account_id, target, catalog, usage, deps_summary, warnings, edition="free", deps=None) -> dict:
    services, unknown = [], []
    for ns in sorted(usage):
        if not catalog.known(ns):
            unknown.append({"namespace": ns, "resources": usage[ns]["count"], "regions": usage[ns]["regions"]})
            continue
        services.append({
            "service": ns,
            "resources": usage[ns]["count"],
            "regions": usage[ns]["regions"],
            "status": catalog.status(ns),
            "reason": catalog.reason(ns),
        })
    order = {"wait": 0, "verify": 1, "ready": 2}
    services.sort(key=lambda s: (order[s["status"]], s["service"]))
    summary = {k: sum(1 for s in services if s["status"] == k) for k in ("ready", "verify", "wait")}
    summary["dependencies"] = sum(d["count"] for d in deps_summary)
    summary["outside_control"] = sum(d["count"] for d in deps_summary if d["group"] == "outside_control")
    result = {
        "tool": "sovlens",
        "edition": edition,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "account_id": account_id,
        "target_region": target,
        "catalog_source": f"ESC User Guide ({catalog.guide_checked}) + botocore {catalog.botocore_version} endpoint data + overrides",
        "summary": summary,
        "services": services,
        "unrecognised": unknown,
        "dependencies_summary": deps_summary,
        "warnings": warnings,
        "disclaimer": "Technical readiness only. Not legal or compliance advice. Verify 'Verify' items against AWS Capabilities by Region.",
    }
    if deps is not None:
        result["dependencies"] = deps
    return result


def dependencies_section(r: dict) -> str:
    """Free edition: counts per kind. Sovlens Pro replaces this section."""
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(GROUPS[d['group']])}</td><td>{e(KINDS[d['kind']][1])}</td><td>{d['count']}</td></tr>"
        for d in r["dependencies_summary"]
    ) or "<tr><td colspan='3'>Nothing found.</td></tr>"
    return ("<h2>Cross-partition dependencies</h2><div class='wrap'><table>"
            "<tr><th>Group</th><th>What</th><th>Count</th></tr>"
            f"{rows}</table></div><p class='meta' style='margin-top:10px'>{e(PRO_NOTE)}</p>")


def to_html(r: dict, deps_html: str | None = None) -> str:
    e = html.escape
    tiles = "".join(
        f"<div class='tile'><b style='color:{c}'>{r['summary'][k]}</b><span>{e(t)}</span></div>"
        for k, t, c in [("ready", "Services ready", COLOR["ready"]), ("verify", "To verify", COLOR["verify"]),
                        ("wait", "Must wait", COLOR["wait"]),
                        ("outside_control", "Dependencies outside your control", "#AFC2FF")]
    )
    rows = "".join(
        f"<tr><td><code>{e(s['service'])}</code></td><td>{s['resources']}</td><td>{e(', '.join(s['regions']))}</td>"
        f"<td><span class='pill' style='color:{COLOR[s['status']]}'>{LABEL[s['status']]}</span></td><td>{e(s['reason'])}</td></tr>"
        for s in r["services"]
    ) or "<tr><td colspan='5'>No resources found.</td></tr>"
    unknown = ""
    if r["unrecognised"]:
        items = ", ".join(f"<code>{e(u['namespace'])}</code> ({u['resources']})" for u in r["unrecognised"])
        unknown = f"<p class='meta' style='margin-top:10px'>Other tagged resource types, not assessed: {items}</p>"
    warn = "".join(f"<li>{e(w)}</li>" for w in r["warnings"]) or "<li>None</li>"
    deps = deps_html if deps_html is not None else dependencies_section(r)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sovlens report {e(r['account_id'])}</title>
<style>body{{margin:0;background:#0E1116;color:#E8EAF0;font:15px/1.55 system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:40px 20px}}h1{{font-size:28px;margin:0 0 4px}}h2{{font-size:19px;margin:36px 0 12px}}
p.meta{{color:#9AA3B2;margin:0 0 24px}}.tiles{{display:flex;flex-wrap:wrap;gap:12px}}
.tile{{flex:1 1 160px;background:#151A22;border:1px solid #262D3A;border-radius:12px;padding:14px 16px}}
.tile b{{display:block;font-size:30px;line-height:1.1}}.tile span{{color:#B4BCCA;font-size:13px}}
.wrap{{overflow-x:auto;border:1px solid #262D3A;border-radius:12px}}table{{border-collapse:collapse;width:100%;min-width:720px}}
th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid #222937;vertical-align:top}}th{{color:#9AA3B2;font-size:12px;text-transform:uppercase;letter-spacing:.05em}}
code{{font:13px ui-monospace,monospace;word-break:break-all}}.pill{{font-weight:600}}li{{color:#B4BCCA}}footer{{color:#8A93A3;font-size:13px;margin-top:32px}}</style></head>
<body><main><h1>ESC readiness report</h1>
<p class="meta">Account {e(r['account_id'])} &rarr; {e(r['target_region'])} &middot; {e(r['generated_at'])} &middot; {e(r['catalog_source'])}</p>
<div class="tiles">{tiles}</div>
<h2>Services in use</h2><div class="wrap"><table><tr><th>Service</th><th>Resources</th><th>Regions</th><th>Status</th><th>Why</th></tr>{rows}</table></div>
{unknown}
{deps}
<h2>Scan warnings</h2><ul>{warn}</ul>
<footer>{e(r['disclaimer'])} Sovlens is not affiliated with Amazon Web Services.</footer></main></body></html>"""

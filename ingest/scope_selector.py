"""Reusable scope selector widget for ingest operator pages.

Renders a two-column multi-select (Clients / Devices) with live JS
search and batched submission support.  Any page that needs a df
scope picker imports load_scope_choices() + render_scope_selector().

Batch behaviour
───────────────
When the operator selects more than one item (or types a comma-separated
list), the JS intercepts the submit and fires one GET request per scope
value to the given action URL, waits for all 202s, then redirects to
redirect_url.  Single selections fall through as a normal GET.

Usage in a handler
──────────────────
    orgs, devices = scope_selector.load_scope_choices()
    html = scope_selector.render_scope_selector(
        orgs, devices,
        action="/run/software/enqueue",
        submit_label="Queue now",
        redirect_url="/run/software/queue",
    )
    # Embed html inside your page body.
"""

from __future__ import annotations

import logging
from html import escape

log = logging.getLogger(__name__)


def load_scope_choices() -> tuple[list[tuple[int, str]], list[tuple[int, str, int]]]:
    """Return (orgs, devices) for the selector.

    orgs    — list of (org_id, name)
    devices — list of (device_id, display_name, org_id)
    """
    from ingest import db

    orgs: list[tuple[int, str]] = []
    devices: list[tuple[int, str, int]] = []
    try:
        with db.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name FROM ninja_core.organizations ORDER BY name"
            )
            orgs = cur.fetchall()
            cur.execute(
                """
                SELECT id,
                       COALESCE(display_name, system_name, 'Device ' || id::text),
                       organization_id
                FROM ninja_core.devices
                WHERE is_current = TRUE
                ORDER BY display_name, system_name
                LIMIT 5000
                """
            )
            devices = cur.fetchall()
    except Exception:
        log.warning("scope_selector: failed to load choices from DB", exc_info=True)
    return orgs, devices


def render_scope_selector(
    orgs: list[tuple[int, str]],
    devices: list[tuple[int, str, int]],
    *,
    action: str,
    submit_label: str,
    redirect_url: str,
    links_html: str = "",
) -> str:
    """Return a self-contained HTML fragment: styles + two-column selector + form.

    action        — form/fetch target URL (must accept ?df=…&confirm=1)
    submit_label  — text on the submit button
    redirect_url  — where JS redirects after batched multi-submission
    links_html    — optional <p>…</p> of nav links rendered below the form
    """
    org_map = {oid: name for oid, name in orgs}

    org_opts = "\n".join(
        f'<option value="org={oid}">{escape(name)} (org={oid})</option>'
        for oid, name in orgs
    )
    dev_opts = "\n".join(
        f'<option value="id={did}">'
        f'{escape(dname)} — {escape(org_map.get(org_id, str(org_id)))} (id={did})'
        f'</option>'
        for did, dname, org_id in devices
    )

    # Escape braces for Python f-string; actual JS uses single braces.
    return f"""
<style>
  .ss-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
    margin-bottom: 1.25rem;
  }}
  @media (max-width: 600px) {{ .ss-grid {{ grid-template-columns: 1fr; }} }}
  .ss-col label {{
    display: block;
    font-weight: 700;
    margin-bottom: 4px;
    font-size: 14px;
  }}
  .ss-search {{
    width: 100%;
    box-sizing: border-box;
    font-size: 13px;
    padding: 6px 9px;
    border: 1px solid #bcccdc;
    border-bottom: none;
    border-radius: 4px 4px 0 0;
  }}
  .ss-list {{
    width: 100%;
    box-sizing: border-box;
    font-size: 13px;
    border: 1px solid #bcccdc;
    border-radius: 0 0 4px 4px;
    height: 200px;
    background: white;
  }}
  .ss-badge {{
    font-size: 12px;
    color: #0b69a3;
    min-height: 16px;
    margin-top: 3px;
  }}
  .ss-df {{
    width: 100%;
    box-sizing: border-box;
    font-size: 14px;
    padding: 8px 10px;
    border: 1px solid #bcccdc;
    border-radius: 4px;
    font-family: monospace;
    margin-top: 4px;
  }}
  .ss-hint {{ color: #52606d; font-size: 12px; margin: 4px 0 0; }}
  .ss-btn {{
    margin-top: 14px;
    padding: 9px 20px;
    font-size: 14px;
    font-weight: 700;
    background: #0b69a3;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
  }}
  .ss-btn:hover {{ background: #0a5c8f; }}
  .ss-btn:disabled {{ background: #9db8cc; cursor: default; }}
  .ss-status {{ margin-top: 8px; font-size: 13px; color: #52606d; min-height: 18px; }}
</style>

<div class="ss-grid">
  <div class="ss-col">
    <label>Clients</label>
    <input class="ss-search" type="search" placeholder="Search clients…"
           oninput="ssFilter('ss-orgs',this.value)">
    <select id="ss-orgs" class="ss-list" multiple
            onchange="ssSelectionChanged()">
      {org_opts}
    </select>
    <div class="ss-badge" id="ss-orgs-badge"></div>
  </div>
  <div class="ss-col">
    <label>Devices</label>
    <input class="ss-search" type="search" placeholder="Search devices…"
           oninput="ssFilter('ss-devs',this.value)">
    <select id="ss-devs" class="ss-list" multiple
            onchange="ssSelectionChanged()">
      {dev_opts}
    </select>
    <div class="ss-badge" id="ss-devs-badge"></div>
  </div>
</div>

<label style="display:block;font-weight:700;font-size:14px;margin-bottom:4px;">
  Scope (df)
  <span style="font-weight:400;color:#52606d;font-size:12px;">
    — filled automatically, or type manually
  </span>
</label>
<input id="ss-df" class="ss-df"
       placeholder="org=123  ·  id=456  ·  org=123 AND id=456"
       oninput="ssManualEdit()"
       autocomplete="off">
<p class="ss-hint">
  Select multiple clients or devices — each will be submitted separately.
  Ctrl/⌘-click to multi-select; shift-click for a range.
</p>
<button class="ss-btn" id="ss-submit" onclick="ssSubmit()">{submit_label}</button>
<div class="ss-status" id="ss-status"></div>

{links_html}

<script>
(function() {{
  var ACTION       = {escape(action)!r};
  var REDIRECT     = {escape(redirect_url)!r};
  var manualEdit   = false;

  // Live-filter visible options in a <select multiple>.
  window.ssFilter = function(id, q) {{
    q = q.toLowerCase();
    var sel = document.getElementById(id);
    for (var i = 0; i < sel.options.length; i++) {{
      var show = !q || sel.options[i].text.toLowerCase().indexOf(q) !== -1;
      sel.options[i].style.display = show ? '' : 'none';
    }}
  }};

  window.ssManualEdit = function() {{ manualEdit = true; }};

  window.ssSelectionChanged = function() {{
    if (manualEdit) return;
    var vals = ssGetSelected();
    document.getElementById('ss-df').value = vals.length === 1 ? vals[0] : '';
    var oc = ssGetSelectedFrom('ss-orgs').length;
    var dc = ssGetSelectedFrom('ss-devs').length;
    document.getElementById('ss-orgs-badge').textContent =
      oc ? oc + ' client' + (oc > 1 ? 's' : '') + ' selected' : '';
    document.getElementById('ss-devs-badge').textContent =
      dc ? dc + ' device' + (dc > 1 ? 's' : '') + ' selected' : '';
  }};

  function ssGetSelectedFrom(id) {{
    var sel = document.getElementById(id);
    var out = [];
    for (var i = 0; i < sel.options.length; i++) {{
      if (sel.options[i].selected) out.push(sel.options[i].value);
    }}
    return out;
  }}

  function ssGetSelected() {{
    return ssGetSelectedFrom('ss-orgs').concat(ssGetSelectedFrom('ss-devs'));
  }}

  window.ssSubmit = async function() {{
    var manualDf = document.getElementById('ss-df').value.trim();
    var targets  = manualDf ? [manualDf] : ssGetSelected();

    if (!targets.length) {{
      document.getElementById('ss-status').textContent =
        'Select at least one client or device, or type a df value.';
      return;
    }}

    var btn    = document.getElementById('ss-submit');
    var status = document.getElementById('ss-status');
    btn.disabled = true;

    if (targets.length === 1) {{
      // Single: normal navigation so the page response shows directly.
      window.location = ACTION + '?df=' + encodeURIComponent(targets[0]) + '&confirm=1';
      return;
    }}

    // Multiple: fire one request per target, then redirect to queue.
    status.textContent = 'Queuing 0 / ' + targets.length + '…';
    var done = 0;
    var errs = 0;
    for (var i = 0; i < targets.length; i++) {{
      try {{
        var r = await fetch(ACTION + '?df=' + encodeURIComponent(targets[i]) + '&confirm=1');
        if (r.ok || r.status === 202 || r.status === 303) {{ done++; }}
        else {{ errs++; }}
      }} catch(e) {{ errs++; }}
      status.textContent = 'Queuing ' + (done + errs) + ' / ' + targets.length + '…';
    }}
    status.textContent = 'Done — ' + done + ' queued' + (errs ? ', ' + errs + ' errors' : '') + '. Redirecting…';
    setTimeout(function() {{ window.location = REDIRECT; }}, 800);
  }};
}})();
</script>
"""

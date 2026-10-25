from pathlib import Path
source = Path(r'D:\AgentWindTunnel\docs\reports\delivery-2026-10-24\verify_delivery_verify.py').read_text(encoding='utf-8').split("if __name__ == '__main__':")[0]
source = source.replace("                page.locator('#btnRunTests').click()", "                previous_url = page.url\n                page.locator('#btnRunTests').click()\n                page.wait_for_function('(old) => location.href !== old && location.hash.includes(\"run=\")', arg=previous_url)")
source = source.replace("                page.reload(wait_until='networkidle')", "                page.wait_for_function('document.querySelector(\"#panelRunStatusPill\").textContent.includes(\"RUNNING\") || document.querySelector(\"#panelRunStatusPill\").textContent.includes(\"COMPLETED\")')\n                page.reload(wait_until='networkidle')")
source = source.replace("                page.locator('#studioScenariosTbody tr td').first.click()", "                assert data['scenario_runs'], data\n                assert data['total_scenarios'] == (20 if suite == 'dev_suite' else 1)\n                page.locator('#studioScenariosTbody tr.clickable td').first.click()")
source = source.replace("            for section in ['run-history','comparisons','settings']:", '''            for fmt in ['json','md']:
                with page.expect_download() as download:
                    page.get_by_role('button', name='JSON' if fmt == 'json' else 'Report', exact=True).click()
                target = REPORT / ('download.'+fmt)
                download.value.save_as(str(target))
                if fmt == 'json': assert json.loads(target.read_text(encoding='utf-8')) == data
                else:
                    content = target.read_text(encoding='utf-8')
                    assert runid in content
                    assert all(s['scenario_version_id'] in content for s in data['scenario_runs'])
                record('Browser download matches saved result: '+fmt)
            for section in ['run-history','comparisons','settings']:''')
exec(source)

def fixes():
    replace('backend/static/index.html', "${m.name} (${m.provider})</option>", "${m.name} (${m.provider})</option>")
    replace('backend/static/index.html', "        `).join('');\n      } catch (e) {\n        console.error('Failed to load models:', e);", "        `).join('');\n        handleProviderChange();\n      } catch (e) {\n        console.error('Failed to load models:', e);")
    replace('backend/agent/agent_loop.py', '        self.unresolved_tasks: List[Dict[str, Any]] = []', '        self.unresolved_tasks: List[Dict[str, Any]] = []\n        self.pending_timeout_events: List[Dict[str, Any]] = []')
    replace('backend/agent/agent_loop.py', '            self.trace_logger.log_event(\n                event_type="TOOL_TIMEOUT",', '            self.pending_timeout_events.append(dict(\n                event_type="TOOL_TIMEOUT",')
    replace('backend/agent/agent_loop.py', '                duration_ms=duration\n            )\n            # Track unresolved task', '                duration_ms=duration\n            ))\n            # Track unresolved task')
    replace('backend/agent/agent_loop.py', '        for fut in self.active_futures:', '        # Persist timeout evidence outside the deadline-sensitive return path.\n        for event in self.pending_timeout_events:\n            self.trace_logger.log_event(**event)\n        self.pending_timeout_events.clear()\n        for fut in self.active_futures:')
    p = ROOT / 'tests/test_delivery_regressions.py'
    p.write_text(p.read_text(encoding='utf-8') + '''
def test_timeout_evidence_persists_on_settlement():
    from backend.agent.agent_loop import AgentLoop
    from backend.agent.provider import MockToolCallingProvider
    import threading
    released = threading.Event()
    service = Mock()
    service.get_order.side_effect = lambda **kw: released.wait(2)
    logger = Mock()
    loop = AgentLoop(service, logger, MockToolCallingProvider(), tool_timeout_sec=0.01)
    try:
        output, error = loop._execute_tool_with_timeout("c1", "get_order", {"order_id":"o1"})
        assert output is None and "Gateway Timeout" in error
        assert loop.unresolved_tasks
        assert loop.pending_timeout_events
    finally:
        released.set()
        loop.settle_in_flight_tasks()
    assert not loop.pending_timeout_events
    assert any(c.kwargs.get("event_type") == "TOOL_TIMEOUT" for c in logger.log_event.call_args_list)
''', encoding='utf-8')
    print('Fixed provider default and timeout logging latency; added timeout evidence regression.', flush=True)

if __name__ == '__main__':
    {'fixes':fixes,'tests':run_tests,'browser':browser}[sys.argv[1]]()

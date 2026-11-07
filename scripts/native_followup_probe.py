"""Isolated follow-up evidence; never overwrites NATIVE_TESTS.json."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from native_release_probe import Probe, ROOT


class Followup(Probe):
    def save(self):
        self.report['counts'] = dict(Counter(x['outcome'] for x in self.report['actions']))
        payload = json.dumps(self.report, ensure_ascii=False, indent=2)
        (self.root / 'report.json').write_text(payload, encoding='utf-8')

    def run(self):
        from skills.browser.handler import WindowsBrowserAdapter
        original = WindowsBrowserAdapter.snapshot
        trace = []
        def snapshot(adapter, window, api):
            try:
                result = original(adapter, window, api)
                trace.append({'tabs': result.tabs, 'selected': result.selected,
                              'document_id': result.document_id})
                return result
            except Exception as exc:
                trace.append({'error': type(exc).__name__, 'hresult': getattr(exc, 'hresult', None),
                              'reason': str(exc)})
                raise
        WindowsBrowserAdapter.snapshot = snapshot
        try:
            self.browser()
        except Exception as exc:
            self.record('browser', 'probe_error', outcome='failed', note=type(exc).__name__ + ': ' + str(exc))
        finally:
            WindowsBrowserAdapter.snapshot = original
            self.report['uia_trace'] = trace
            self.cleanup()
        self.report['finished'] = datetime.now(timezone.utc).isoformat()
        self.save()
        print(json.dumps({'report': str(self.root / 'report.json'), 'counts': self.report['counts']}), flush=True)
        return int(bool(self.report['counts'].get('failed')))


if __name__ == '__main__':
    raise SystemExit(Followup().run())

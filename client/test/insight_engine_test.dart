import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vira_link/core/catalog/app_catalog.dart';
import 'package:vira_link/core/models/app_usage.dart';
import 'package:vira_link/core/models/device_signals.dart';
import 'package:vira_link/core/models/focus_session.dart';
import 'package:vira_link/data/storage/focus_ledger.dart';
import 'package:vira_link/services/insights/insight_engine.dart';

void main() {
  test('focus ledger starts, stops and lists sessions', () async {
    SharedPreferences.setMockInitialValues({});
    final ledger = await FocusLedger.open();
    final session = FocusSession(
      id: 'focus-1',
      label: 'Study',
      startedAt: DateTime.now().toUtc().subtract(const Duration(minutes: 25)),
      plannedMinutes: 25,
    );
    await ledger.start(session);
    expect((await ledger.active())?.id, 'focus-1');
    final stopped = await ledger.stop(markCompleted: true);
    expect(stopped, isNotNull);
    expect(stopped!.completed, isTrue);
    expect(await ledger.active(), isNull);
    expect((await ledger.recent()).single.id, 'focus-1');
  });

  test('insight engine surfaces distraction, unlocks and health warnings', () {
    final day = UsageDay(
      date: '2026-01-01',
      apps: {
        'instagram': const AppUsageSample(
          packageName: 'instagram',
          label: 'Instagram',
          foregroundMs: 90 * 60 * 1000,
          category: AppCategory.social,
        ),
        'vscode': const AppUsageSample(
          packageName: 'vscode',
          label: 'VS Code',
          foregroundMs: 30 * 60 * 1000,
          category: AppCategory.productivity,
        ),
      },
    );
    const session = SessionDay(
      date: '2026-01-01',
      interactiveMs: 3 * 60 * 60 * 1000,
      unlocks: 45,
      currentSessionMs: 50 * 60 * 1000,
    );
    const health = DeviceHealthSnapshot(
      storageFreeBytes: 5,
      storageTotalBytes: 100,
    );
    final report = InsightEngine.build(
      usage: [day],
      sessions: [session],
      focus: const [],
      health: health,
    );
    final ids = report.findings.map((finding) => finding.id).toList();
    expect(ids, contains('long-screen-day'));
    expect(ids, contains('current-session-break'));
    expect(ids, contains('distraction-share'));
    expect(ids, contains('frequent-unlocks'));
    expect(ids.any((id) => id.startsWith('health-')), isTrue);
    expect(report.screenMs, 3 * 60 * 60 * 1000);
    expect(report.unlocks, 45);
  });

  test('insight engine recognises a productive mix', () {
    final day = UsageDay(
      date: '2026-01-01',
      apps: {
        'classroom': const AppUsageSample(
          packageName: 'classroom',
          label: 'Classroom',
          foregroundMs: 60 * 60 * 1000,
          category: AppCategory.education,
        ),
      },
    );
    final report = InsightEngine.build(
      usage: [day],
      sessions: const [],
      focus: const [],
    );
    expect(
      report.findings.map((finding) => finding.id),
      contains('strong-focus-mix'),
    );
  });
}

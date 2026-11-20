import '../../core/catalog/app_catalog.dart';
import '../../core/models/app_usage.dart';
import '../../core/models/device_signals.dart';
import '../../core/models/focus_session.dart';
import '../../core/utils/duration_format.dart';

enum InsightTone { success, info, warning, neutral }

class InsightFinding {
  const InsightFinding({
    required this.id,
    required this.title,
    required this.body,
    required this.tone,
    this.recommendation,
  });

  final String id;
  final String title;
  final String body;
  final InsightTone tone;
  final String? recommendation;
}

class InsightReport {
  const InsightReport({
    required this.findings,
    required this.screenMs,
    required this.appMs,
    required this.focusSessionMs,
    required this.focusSessionCount,
    required this.unlocks,
    required this.productiveMs,
    required this.distractionMs,
  });

  final List<InsightFinding> findings;
  final int screenMs;
  final int appMs;
  final int focusSessionMs;
  final int focusSessionCount;
  final int unlocks;
  final int productiveMs;
  final int distractionMs;
}

class InsightEngine {
  static InsightReport build({
    required List<UsageDay> usage,
    required List<SessionDay> sessions,
    required List<FocusSession> focus,
    DeviceHealthSnapshot? health,
    DateTime? now,
  }) {
    final appMs = usage.fold(0, (total, day) => total + day.totalForegroundMs);
    final screenMs = sessions.fold(
      0,
      (total, day) => total + day.interactiveMs,
    );
    final unlocks = sessions.fold(0, (total, day) => total + day.unlocks);
    final focusSessionMs = focus.fold(
      0,
      (total, session) => total + session.durationMs,
    );
    final focusSessionCount = focus.length;
    final categories = <String, int>{};
    for (final day in usage) {
      for (final app in day.apps.values) {
        categories[app.category] =
            (categories[app.category] ?? 0) + app.foregroundMs;
      }
    }
    final productiveMs =
        (categories[AppCategory.productivity] ?? 0) +
        (categories[AppCategory.education] ?? 0);
    final distractionMs =
        (categories[AppCategory.social] ?? 0) +
        (categories[AppCategory.entertainment] ?? 0) +
        (categories[AppCategory.games] ?? 0);
    final findings = <InsightFinding>[];
    final currentSession = sessions.isEmpty
        ? 0
        : sessions.first.currentSessionMs;

    if (screenMs >= 3 * 60 * 60 * 1000) {
      findings.add(
        InsightFinding(
          id: 'long-screen-day',
          title: 'Long screen day',
          body: 'You have ${formatDurationMs(screenMs)} of screen time in this range.',
          tone: InsightTone.warning,
          recommendation:
              'Take a 5-minute break and move your next deep-work block away from the screen.',
        ),
      );
    }
    if (currentSession >= 45 * 60 * 1000) {
      findings.add(
        InsightFinding(
          id: 'current-session-break',
          title: 'Current session is long',
          body: 'This screen session is ${formatDurationMs(currentSession)} long.',
          tone: InsightTone.warning,
          recommendation: 'Stand up, stretch and look away for a few minutes.',
        ),
      );
    }
    if (appMs >= 60 * 60 * 1000 && distractionMs > productiveMs) {
      findings.add(
        InsightFinding(
          id: 'distraction-share',
          title: 'Distraction is taking the lead',
          body:
              '${formatDurationMs(distractionMs)} went to social, entertainment or games, versus ${formatDurationMs(productiveMs)} for productive or learning apps.',
          tone: InsightTone.warning,
          recommendation:
              'Try a 25-minute focus block and keep the distracting apps closed until it ends.',
        ),
      );
    } else if (appMs >= 60 * 60 * 1000 && productiveMs > 0) {
      findings.add(
        InsightFinding(
          id: 'strong-focus-mix',
          title: 'Strong focus mix',
          body:
              '${formatDurationMs(productiveMs)} went to productive or learning apps. Keep the routine going.',
          tone: InsightTone.success,
        ),
      );
    }
    if (focusSessionCount == 0 && screenMs >= 60 * 60 * 1000) {
      findings.add(
        const InsightFinding(
          id: 'start-focus-session',
          title: 'No focus sessions yet',
          body: 'Deliberate focus blocks make it easier to separate work from browsing.',
          tone: InsightTone.info,
          recommendation: 'Start a 25-minute focus session from the card above.',
        ),
      );
    }
    if (unlocks >= 40) {
      findings.add(
        InsightFinding(
          id: 'frequent-unlocks',
          title: 'Frequent unlocks',
          body: '$unlocks unlocks were recorded in this range.',
          tone: InsightTone.info,
          recommendation:
              'Batch notifications or leave the phone face-down during your next focus block.',
        ),
      );
    }
    if (health != null) {
      for (final warning in health.warnings) {
        findings.add(
          InsightFinding(
            id: 'health-${warning.hashCode}',
            title: 'Device health warning',
            body: warning,
            tone: InsightTone.warning,
            recommendation:
                'Free up storage, close background apps or let the device cool down.',
          ),
        );
      }
    }
    if (findings.isEmpty) {
      findings.add(
        const InsightFinding(
          id: 'collecting',
          title: 'Collecting a baseline',
          body:
              'Keep capture on for a few hours. VIRA will surface patterns once there is enough local data.',
          tone: InsightTone.neutral,
        ),
      );
    }
    return InsightReport(
      findings: findings.take(6).toList(),
      screenMs: screenMs,
      appMs: appMs,
      focusSessionMs: focusSessionMs,
      focusSessionCount: focusSessionCount,
      unlocks: unlocks,
      productiveMs: productiveMs,
      distractionMs: distractionMs,
    );
  }
}

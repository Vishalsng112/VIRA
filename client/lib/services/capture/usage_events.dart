import '../../core/catalog/app_catalog.dart';
import '../../core/config/app_config.dart';
import '../../core/models/app_usage.dart';
import '../../core/models/captured_event.dart';
import '../../core/utils/ids.dart';

/// Builds the shared app-usage and focus events used by both the Android
/// UsageStats collector and the desktop active-window collector.
List<CapturedEvent> buildUsageEvents({
  required List<AppUsageSample> samples,
  required int windowSeconds,
  required String captureMethod,
  String? platform,
}) {
  if (samples.isEmpty) return const [];
  final sorted = samples.toList()
    ..sort((a, b) => b.foregroundMs.compareTo(a.foregroundMs));
  final total = sorted.fold(0, (sum, sample) => sum + sample.foregroundMs);
  final categories = <String, int>{};
  for (final sample in sorted) {
    categories[sample.category] =
        (categories[sample.category] ?? 0) + sample.foregroundMs;
  }
  final focusMs =
      (categories[AppCategory.productivity] ?? 0) +
      (categories[AppCategory.education] ?? 0);
  final distractionMs =
      (categories[AppCategory.social] ?? 0) +
      (categories[AppCategory.entertainment] ?? 0) +
      (categories[AppCategory.games] ?? 0);
  final focusShare = focusMs + distractionMs == 0
      ? 0.0
      : focusMs / (focusMs + distractionMs);
  final focusState = total < 60000
      ? 'idle'
      : focusShare >= 0.7
      ? 'focused'
      : focusShare >= 0.4
      ? 'mixed'
      : 'distracted';
  final now = DateTime.now().toUtc();
  final limited = sorted.take(80).toList();
  return [
    CapturedEvent(
      eventId: newUuidV4(),
      type: 'device.app.usage',
      occurredAt: now,
      sourceComponent: captureMethod,
      payload: {
        'app': appName,
        'client_version': appVersion,
        'capture_method': captureMethod,
        'platform': ?platform,
        'window_seconds': windowSeconds,
        'total_foreground_ms': total,
        'categories': categories,
        'apps': limited.map((sample) => sample.toJson()).toList(),
      },
    ),
    CapturedEvent(
      eventId: newUuidV4(),
      type: 'device.focus.state',
      occurredAt: now,
      sourceComponent: 'focus_engine',
      payload: {
        'app': appName,
        'client_version': appVersion,
        'capture_method': captureMethod,
        'platform': ?platform,
        'state': focusState,
        'focus_ms': focusMs,
        'distraction_ms': distractionMs,
        'focus_score': (focusShare * 100).round(),
        'window_seconds': windowSeconds,
      },
    ),
  ];
}

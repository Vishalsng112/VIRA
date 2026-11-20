import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../../core/models/app_usage.dart';
import '../../core/models/device_signals.dart';

/// Abstraction so collectors can use a real platform bridge or a test fake.
abstract class AppUsageSource {
  Future<bool> hasPermission();

  Future<bool> openSettings();

  Future<List<AppUsageSample>> appUsage({required Duration lookback});
}

abstract class SessionSource {
  Future<bool> hasPermission();

  Future<bool> openSettings();

  Future<SessionSample?> sessionStats({required Duration lookback});
}

abstract class BatterySource {
  Future<BatterySnapshot?> battery();
}

abstract class HealthSource {
  Future<DeviceHealthSnapshot?> health();
}

/// Android UsageStatsManager bridge.
///
/// Requires the user to grant "Usage access" in system settings. No app usage
/// is read until that permission is present.
class AndroidUsageBridge
    implements AppUsageSource, SessionSource, BatterySource, HealthSource {
  static const _channel = MethodChannel('com.vira.link/device');

  bool get _isAndroid =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  @override
  Future<bool> hasPermission() async {
    if (!_isAndroid) return false;
    try {
      return await _channel.invokeMethod<bool>('usagePermission') ?? false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  @override
  Future<bool> openSettings() async {
    if (!_isAndroid) return false;
    try {
      return await _channel.invokeMethod<bool>('openUsageSettings') ?? false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  @override
  Future<List<AppUsageSample>> appUsage({required Duration lookback}) async {
    if (!_isAndroid) return const [];
    try {
      final raw = await _channel.invokeMethod<List<dynamic>>(
        'appUsage',
        {'lookback_ms': lookback.inMilliseconds},
      );
      final samples = (raw ?? const [])
          .whereType<Map>()
          .map((item) {
            final map = Map<String, dynamic>.from(item);
            final packageName = (map['package'] ?? '').toString();
            final label = (map['label'] ?? packageName).toString();
            final millis = (map['foreground_ms'] as num?)?.toInt() ?? 0;
            final lastUsed = (map['last_used_ms'] as num?)?.toInt();
            return AppUsageSample(
              packageName: packageName,
              label: label,
              foregroundMs: millis,
              lastUsedAt: lastUsed == null
                  ? null
                  : DateTime.fromMillisecondsSinceEpoch(
                      lastUsed,
                      isUtc: true,
                    ),
            );
          })
          .where(
            (sample) =>
                sample.packageName.isNotEmpty && sample.foregroundMs > 0,
          )
          .toList();
      return samples;
    } on MissingPluginException {
      return const [];
    } on PlatformException {
      return const [];
    }
  }

  @override
  Future<SessionSample?> sessionStats({required Duration lookback}) async {
    if (!_isAndroid) return null;
    try {
      final raw = await _channel.invokeMethod<Map<dynamic, dynamic>>(
        'sessionStats',
        {'lookback_ms': lookback.inMilliseconds},
      );
      if (raw == null) return null;
      final map = Map<String, dynamic>.from(raw);
      return SessionSample(
        interactiveMs: (map['interactive_ms'] as num?)?.toInt() ?? 0,
        screenOnEvents: (map['screen_on_events'] as num?)?.toInt() ?? 0,
        screenOffEvents: (map['screen_off_events'] as num?)?.toInt() ?? 0,
        unlocks: (map['unlocks'] as num?)?.toInt() ?? 0,
        interactions: (map['interactions'] as num?)?.toInt() ?? 0,
        currentSessionMs: (map['current_session_ms'] as num?)?.toInt() ?? 0,
        screenOn: map['screen_on'] == true,
        windowSeconds: (map['window_seconds'] as num?)?.toInt() ?? 0,
      );
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }

  @override
  Future<BatterySnapshot?> battery() async {
    if (!_isAndroid) return null;
    try {
      final raw = await _channel.invokeMethod<Map<dynamic, dynamic>>('battery');
      if (raw == null) return null;
      return BatterySnapshot.fromJson(Map<String, dynamic>.from(raw));
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }

  @override
  Future<DeviceHealthSnapshot?> health() async {
    if (!_isAndroid) return null;
    try {
      final raw = await _channel.invokeMethod<Map<dynamic, dynamic>>('health');
      if (raw == null) return null;
      return DeviceHealthSnapshot.fromJson(Map<String, dynamic>.from(raw));
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }
}

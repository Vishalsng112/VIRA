/// Battery state from the OS. Fields are nullable because platform support
/// differs and partial data is still useful.
class BatterySnapshot {
  const BatterySnapshot({
    this.levelPercent,
    this.charging,
    this.temperatureC,
    this.plugged,
    this.health,
  });

  final int? levelPercent;
  final bool? charging;
  final double? temperatureC;
  final String? plugged;
  final String? health;

  bool get isLow =>
      levelPercent != null && levelPercent! <= 15 && charging != true;

  Map<String, dynamic> toJson() => {
    if (levelPercent != null) 'level_percent': levelPercent,
    if (charging != null) 'charging': charging,
    if (temperatureC != null) 'temperature_c': temperatureC,
    if (plugged != null) 'plugged': plugged,
    if (health != null) 'health': health,
  };

  static BatterySnapshot? fromJson(Map<String, dynamic> json) {
    final level = (json['level_percent'] as num?)?.toInt();
    final charging = json['charging'];
    final temperature = (json['temperature_c'] as num?)?.toDouble();
    final plugged = json['plugged']?.toString();
    final health = json['health']?.toString();
    if (level == null &&
        charging == null &&
        temperature == null &&
        plugged == null &&
        health == null) {
      return null;
    }
    return BatterySnapshot(
      levelPercent: level,
      charging: charging is bool ? charging : null,
      temperatureC: temperature,
      plugged: plugged,
      health: health,
    );
  }
}

class SessionSample {
  const SessionSample({
    required this.interactiveMs,
    required this.screenOnEvents,
    required this.screenOffEvents,
    required this.unlocks,
    required this.interactions,
    required this.currentSessionMs,
    required this.screenOn,
    required this.windowSeconds,
  });

  final int interactiveMs;
  final int screenOnEvents;
  final int screenOffEvents;
  final int unlocks;
  final int interactions;
  final int currentSessionMs;
  final bool screenOn;
  final int windowSeconds;

  Map<String, dynamic> toJson() => {
    'interactive_ms': interactiveMs,
    'screen_on_events': screenOnEvents,
    'screen_off_events': screenOffEvents,
    'unlocks': unlocks,
    'interactions': interactions,
    'current_session_ms': currentSessionMs,
    'screen_on': screenOn,
    'window_seconds': windowSeconds,
  };
}

class SessionDay {
  const SessionDay({
    required this.date,
    this.interactiveMs = 0,
    this.screenOnEvents = 0,
    this.screenOffEvents = 0,
    this.unlocks = 0,
    this.interactions = 0,
    this.longestSessionMs = 0,
    this.currentSessionMs = 0,
  });

  final String date;
  final int interactiveMs;
  final int screenOnEvents;
  final int screenOffEvents;
  final int unlocks;
  final int interactions;
  final int longestSessionMs;
  final int currentSessionMs;

  Map<String, dynamic> toJson() => {
    'date': date,
    'interactive_ms': interactiveMs,
    'screen_on_events': screenOnEvents,
    'screen_off_events': screenOffEvents,
    'unlocks': unlocks,
    'interactions': interactions,
    'longest_session_ms': longestSessionMs,
    'current_session_ms': currentSessionMs,
  };
}

class DeviceHealthSnapshot {
  const DeviceHealthSnapshot({
    this.storageFreeBytes,
    this.storageTotalBytes,
    this.memoryAvailableBytes,
    this.memoryTotalBytes,
    this.thermalC,
    this.thermalStatus,
    this.batteryTemperatureC,
  });

  final int? storageFreeBytes;
  final int? storageTotalBytes;
  final int? memoryAvailableBytes;
  final int? memoryTotalBytes;
  final double? thermalC;
  final String? thermalStatus;
  final double? batteryTemperatureC;

  int? get storagePercent {
    final total = storageTotalBytes;
    final free = storageFreeBytes;
    if (total == null || free == null || total <= 0) return null;
    return ((total - free) / total * 100).round();
  }

  int? get memoryPercent {
    final total = memoryTotalBytes;
    final available = memoryAvailableBytes;
    if (total == null || available == null || total <= 0) return null;
    return ((total - available) / total * 100).round();
  }

  bool get storageLow => (storagePercent ?? 0) >= 90;
  bool get memoryHigh => (memoryPercent ?? 0) >= 90;
  bool get runningWarm => (thermalC ?? 0) >= 45 || (batteryTemperatureC ?? 0) >= 42;

  List<String> get warnings => [
    if (storageLow) 'Low storage: $storagePercent% used',
    if (memoryHigh) 'High memory pressure: $memoryPercent% used',
    if (runningWarm) 'Device is running warm',
  ];

  Map<String, dynamic> toJson() => {
    'storage_free_bytes': ?storageFreeBytes,
    'storage_total_bytes': ?storageTotalBytes,
    'storage_percent': ?storagePercent,
    'memory_available_bytes': ?memoryAvailableBytes,
    'memory_total_bytes': ?memoryTotalBytes,
    'memory_percent': ?memoryPercent,
    'thermal_c': ?thermalC,
    'thermal_status': ?thermalStatus,
    'battery_temperature_c': ?batteryTemperatureC,
    'warnings': warnings,
  };

  static DeviceHealthSnapshot? fromJson(Map<String, dynamic> json) {
    final hasData = json.values.any((value) => value != null);
    if (!hasData) return null;
    return DeviceHealthSnapshot(
      storageFreeBytes: (json['storage_free_bytes'] as num?)?.toInt(),
      storageTotalBytes: (json['storage_total_bytes'] as num?)?.toInt(),
      memoryAvailableBytes: (json['memory_available_bytes'] as num?)?.toInt(),
      memoryTotalBytes: (json['memory_total_bytes'] as num?)?.toInt(),
      thermalC: (json['thermal_c'] as num?)?.toDouble(),
      thermalStatus: json['thermal_status']?.toString(),
      batteryTemperatureC: (json['battery_temperature_c'] as num?)?.toDouble(),
    );
  }
}

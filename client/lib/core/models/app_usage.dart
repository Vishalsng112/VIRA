import '../utils/ids.dart';

/// Foreground time for one application during one capture interval.
class AppUsageSample {
  const AppUsageSample({
    required this.packageName,
    required this.label,
    required this.foregroundMs,
    this.category = 'other',
    this.lastUsedAt,
  });

  final String packageName;
  final String label;
  final int foregroundMs;
  final String category;
  final DateTime? lastUsedAt;

  AppUsageSample copyWith({
    String? label,
    int? foregroundMs,
    String? category,
    DateTime? lastUsedAt,
  }) => AppUsageSample(
    packageName: packageName,
    label: label ?? this.label,
    foregroundMs: foregroundMs ?? this.foregroundMs,
    category: category ?? this.category,
    lastUsedAt: lastUsedAt ?? this.lastUsedAt,
  );

  AppUsageSample merge(AppUsageSample other) => AppUsageSample(
    packageName: packageName,
    label: other.label,
    foregroundMs: foregroundMs + other.foregroundMs,
    category: other.category,
    lastUsedAt: other.lastUsedAt ?? lastUsedAt,
  );

  Map<String, dynamic> toJson() => {
    'package': packageName,
    'label': label,
    'category': category,
    'foreground_ms': foregroundMs,
    if (lastUsedAt != null) 'last_used_at': isoUtc(lastUsedAt!),
  };

  Map<String, dynamic> toStorageJson() => {
    ...toJson(),
    'package': packageName,
  };

  static AppUsageSample fromJson(Map<String, dynamic> json) => AppUsageSample(
    packageName: (json['package'] ?? json['package_name'] ?? '').toString(),
    label: (json['label'] ?? json['package'] ?? 'Unknown app').toString(),
    foregroundMs: (json['foreground_ms'] as num?)?.toInt() ?? 0,
    category: (json['category'] ?? 'other').toString(),
    lastUsedAt: parseUtc(json['last_used_at']),
  );
}

class UsageDay {
  const UsageDay({required this.date, required this.apps});

  final String date;
  final Map<String, AppUsageSample> apps;

  int get totalForegroundMs =>
      apps.values.fold(0, (total, app) => total + app.foregroundMs);

  List<AppUsageSample> get sortedApps {
    final values = apps.values.toList()
      ..sort((a, b) => b.foregroundMs.compareTo(a.foregroundMs));
    return values;
  }

  AppUsageSample? get topApp => sortedApps.isEmpty ? null : sortedApps.first;

  Map<String, int> categoryTotals() {
    final totals = <String, int>{};
    for (final app in apps.values) {
      totals[app.category] = (totals[app.category] ?? 0) + app.foregroundMs;
    }
    return totals;
  }

  Map<String, dynamic> toJson() => {
    'date': date,
    'apps': {
      for (final entry in apps.entries) entry.key: entry.value.toStorageJson(),
    },
  };
}

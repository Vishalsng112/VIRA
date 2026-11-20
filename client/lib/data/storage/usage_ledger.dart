import 'dart:async';
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../core/models/app_usage.dart';

/// Local daily rollup of app foreground time.
///
/// The server receives interval events, but the client keeps its own compact
/// ledger so Insights and offline summaries work without the network.
class UsageLedger {
  UsageLedger._(this._prefs);

  static const _key = 'usage.ledger.v1';
  static const _maxDays = 30;

  final SharedPreferences _prefs;
  Future<void> _tail = Future<void>.value();

  static Future<UsageLedger> open() async =>
      UsageLedger._(await SharedPreferences.getInstance());

  Future<T> _serial<T>(Future<T> Function() action) {
    final completer = Completer<T>();
    _tail = _tail.then((_) async {
      try {
        completer.complete(await action());
      } on Object catch (error, stack) {
        completer.completeError(error, stack);
      }
    });
    return completer.future;
  }

  Map<String, Map<String, Map<String, dynamic>>> _readAll() {
    final raw = _prefs.getString(_key);
    if (raw == null || raw.isEmpty) return {};
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return {};
      final result = <String, Map<String, Map<String, dynamic>>>{};
      for (final dayEntry in decoded.entries) {
        final day = dayEntry.key.toString();
        final apps = dayEntry.value;
        if (apps is! Map) continue;
        final parsed = <String, Map<String, dynamic>>{};
        for (final appEntry in apps.entries) {
          if (appEntry.value is Map) {
            parsed[appEntry.key.toString()] = Map<String, dynamic>.from(
              appEntry.value as Map,
            );
          }
        }
        result[day] = parsed;
      }
      return result;
    } on Object {
      return {};
    }
  }

  Future<void> _writeAll(
    Map<String, Map<String, Map<String, dynamic>>> all,
  ) => _prefs.setString(_key, jsonEncode(all));

  static String _dayKey(DateTime date) {
    final local = date.toLocal();
    String two(int value) => value.toString().padLeft(2, '0');
    return '${local.year}-${two(local.month)}-${two(local.day)}';
  }

  Future<void> record(List<AppUsageSample> samples, {DateTime? at}) {
    if (samples.isEmpty) return Future<void>.value();
    return _serial(() async {
      final all = _readAll();
      final key = _dayKey(at ?? DateTime.now());
      final apps = all.putIfAbsent(key, () => <String, Map<String, dynamic>>{});
      for (final sample in samples) {
        final previous = apps[sample.packageName];
        final merged = previous == null
            ? sample
            : AppUsageSample.fromJson(previous).merge(sample);
        apps[sample.packageName] = merged.toStorageJson();
      }
      final days = all.keys.toList()..sort((a, b) => b.compareTo(a));
      for (final old in days.skip(_maxDays)) {
        all.remove(old);
      }
      await _writeAll(all);
    });
  }

  Future<UsageDay?> day(DateTime date) async {
    final apps = _readAll()[_dayKey(date)];
    if (apps == null) return null;
    return UsageDay(
      date: _dayKey(date),
      apps: {
        for (final entry in apps.entries)
          entry.key: AppUsageSample.fromJson(entry.value),
      },
    );
  }

  Future<UsageDay> today() async =>
      await day(DateTime.now()) ?? UsageDay(date: _dayKey(DateTime.now()), apps: const {});

  Future<List<UsageDay>> recent({int days = 7}) async {
    final all = _readAll();
    final keys = all.keys.toList()..sort((a, b) => b.compareTo(a));
    return [
      for (final key in keys.take(days))
        UsageDay(
          date: key,
          apps: {
            for (final entry in all[key]!.entries)
              entry.key: AppUsageSample.fromJson(entry.value),
          },
        ),
    ];
  }

  Future<void> clear() => _serial(() => _prefs.remove(_key));
}

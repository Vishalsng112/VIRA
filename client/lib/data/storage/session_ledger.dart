import 'dart:async';
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../core/models/device_signals.dart';

/// Daily screen/session rollup. Kept locally so Insights and break suggestions
/// work offline without re-reading system usage events.
class SessionLedger {
  SessionLedger._(this._prefs);

  static const _key = 'session.ledger.v1';
  static const _maxDays = 30;

  final SharedPreferences _prefs;
  Future<void> _tail = Future<void>.value();

  static Future<SessionLedger> open() async =>
      SessionLedger._(await SharedPreferences.getInstance());

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

  Map<String, Map<String, dynamic>> _readAll() {
    final raw = _prefs.getString(_key);
    if (raw == null || raw.isEmpty) return {};
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return {};
      return {
        for (final entry in decoded.entries)
          if (entry.value is Map)
            entry.key.toString(): Map<String, dynamic>.from(entry.value as Map),
      };
    } on Object {
      return {};
    }
  }

  static String _dayKey(DateTime date) {
    final local = date.toLocal();
    String two(int value) => value.toString().padLeft(2, '0');
    return '${local.year}-${two(local.month)}-${two(local.day)}';
  }

  static SessionDay _dayFrom(String key, Map<String, dynamic> json) => SessionDay(
    date: key,
    interactiveMs: (json['interactive_ms'] as num?)?.toInt() ?? 0,
    screenOnEvents: (json['screen_on_events'] as num?)?.toInt() ?? 0,
    screenOffEvents: (json['screen_off_events'] as num?)?.toInt() ?? 0,
    unlocks: (json['unlocks'] as num?)?.toInt() ?? 0,
    interactions: (json['interactions'] as num?)?.toInt() ?? 0,
    longestSessionMs: (json['longest_session_ms'] as num?)?.toInt() ?? 0,
    currentSessionMs: (json['current_session_ms'] as num?)?.toInt() ?? 0,
  );

  Future<void> record(SessionSample sample, {DateTime? at}) {
    return _serial(() async {
      final all = _readAll();
      final key = _dayKey(at ?? DateTime.now());
      final previous = all[key] == null
          ? const SessionDay(date: '')
          : _dayFrom(key, all[key]!);
      final merged = SessionDay(
        date: key,
        interactiveMs: previous.interactiveMs + sample.interactiveMs,
        screenOnEvents: previous.screenOnEvents + sample.screenOnEvents,
        screenOffEvents: previous.screenOffEvents + sample.screenOffEvents,
        unlocks: previous.unlocks + sample.unlocks,
        interactions: previous.interactions + sample.interactions,
        longestSessionMs: sample.currentSessionMs > previous.longestSessionMs
            ? sample.currentSessionMs
            : previous.longestSessionMs,
        currentSessionMs: sample.currentSessionMs,
      );
      all[key] = merged.toJson();
      final keys = all.keys.toList()..sort((a, b) => b.compareTo(a));
      for (final old in keys.skip(_maxDays)) {
        all.remove(old);
      }
      await _prefs.setString(_key, jsonEncode(all));
    });
  }

  Future<SessionDay?> day(DateTime date) async {
    final key = _dayKey(date);
    final json = _readAll()[key];
    return json == null ? null : _dayFrom(key, json);
  }

  Future<SessionDay> today() async =>
      await day(DateTime.now()) ??
      SessionDay(date: _dayKey(DateTime.now()));

  Future<List<SessionDay>> recent({int days = 7}) async {
    final all = _readAll();
    final keys = all.keys.toList()..sort((a, b) => b.compareTo(a));
    return [
      for (final key in keys.take(days)) _dayFrom(key, all[key]!),
    ];
  }

  Future<void> clear() => _serial(() => _prefs.remove(_key));
}

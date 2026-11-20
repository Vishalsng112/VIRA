import 'dart:async';
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../core/models/focus_session.dart';

class FocusLedger {
  FocusLedger._(this._prefs);

  static const _key = 'focus.ledger.v1';
  static const _maxSessions = 300;

  final SharedPreferences _prefs;
  Future<void> _tail = Future<void>.value();

  static Future<FocusLedger> open() async =>
      FocusLedger._(await SharedPreferences.getInstance());

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

  Map<String, dynamic> _read() {
    final raw = _prefs.getString(_key);
    if (raw == null || raw.isEmpty) return {};
    try {
      final decoded = jsonDecode(raw);
      return decoded is Map ? Map<String, dynamic>.from(decoded) : {};
    } on Object {
      return {};
    }
  }

  Future<void> _write(Map<String, dynamic> data) =>
      _prefs.setString(_key, jsonEncode(data));

  Future<FocusSession?> active() async {
    final active = _read()['active'];
    return active is Map
        ? FocusSession.fromJson(Map<String, dynamic>.from(active))
        : null;
  }

  Future<FocusSession> start(FocusSession session) => _serial(() async {
    final data = _read();
    data['active'] = session.toJson();
    await _write(data);
    return session;
  });

  Future<FocusSession?> stop({bool markCompleted = false}) => _serial(() async {
    final data = _read();
    final raw = data['active'];
    if (raw is! Map) return null;
    final session = FocusSession.fromJson(
      Map<String, dynamic>.from(raw),
    ).finish(completed: markCompleted);
    final sessions = ((data['sessions'] as List?) ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
    sessions.add(session.toJson());
    if (sessions.length > _maxSessions) {
      sessions.removeRange(0, sessions.length - _maxSessions);
    }
    data['sessions'] = sessions;
    data.remove('active');
    await _write(data);
    return session;
  });

  Future<List<FocusSession>> recent({int days = 7}) async {
    final data = _read();
    final cutoff = DateTime.now().toUtc().subtract(Duration(days: days));
    return ((data['sessions'] as List?) ?? const [])
        .whereType<Map>()
        .map((item) => FocusSession.fromJson(Map<String, dynamic>.from(item)))
        .where((session) => session.startedAt.isAfter(cutoff))
        .toList()
      ..sort((a, b) => b.startedAt.compareTo(a.startedAt));
  }

  Future<void> clear() => _serial(() async {
    final current = await active();
    final data = <String, dynamic>{};
    if (current != null) data['active'] = current.toJson();
    await _write(data);
  });
}

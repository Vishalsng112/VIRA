import 'dart:async';
import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../core/models/captured_event.dart';
import '../../core/utils/ids.dart';

/// Durable offline outbox.
///
/// The store is intentionally behind a small interface so a SQLite adapter can
/// replace the JSON implementation later without touching capture or sync.
class OutboxStore {
  OutboxStore._(this._prefs);

  static const _pendingKey = 'outbox.pending';
  static const _historyKey = 'outbox.history';
  static const _sequenceKey = 'outbox.sequence';
  static const _maxPending = 5000;
  static const _maxHistory = 250;

  final SharedPreferences _prefs;
  Future<void> _tail = Future<void>.value();

  static Future<OutboxStore> open() async =>
      OutboxStore._(await SharedPreferences.getInstance());

  List<CapturedEvent> _read(String key) {
    final raw = _prefs.getString(key);
    if (raw == null || raw.isEmpty) return <CapturedEvent>[];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return <CapturedEvent>[];
      return decoded
          .whereType<Map>()
          .map((item) => CapturedEvent.fromJson(Map<String, dynamic>.from(item)))
          .toList();
    } on Object {
      return <CapturedEvent>[];
    }
  }

  Future<void> _write(String key, List<CapturedEvent> value) =>
      _prefs.setString(key, jsonEncode(value.map((e) => e.toJson()).toList()));

  /// Serialises writes so capture and sync cannot clobber each other.
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

  Future<int> depth() async => _read(_pendingKey).length;

  Future<List<CapturedEvent>> pending({int limit = 100}) async =>
      _read(_pendingKey).take(limit).toList();

  Future<List<CapturedEvent>> history() async => _read(_historyKey);

  Future<CapturedEvent> enqueue(CapturedEvent event) => _serial(() async {
    final pending = _read(_pendingKey);
    final sequence = (_prefs.getInt(_sequenceKey) ?? 0) + 1;
    await _prefs.setInt(_sequenceKey, sequence);
    final stored = event.copyWith(
      deviceSequence: sequence,
      capturedAt: DateTime.now().toUtc(),
    );
    pending.add(stored);
    if (pending.length > _maxPending) {
      pending.removeRange(0, pending.length - _maxPending);
    }
    await _write(_pendingKey, pending);
    return stored;
  });

  /// Removes acknowledged events and appends them to the local activity log.
  /// `statuses` values are `sent` or `rejected`.
  Future<void> settle(
    Map<String, EventDeliveryState> statuses, {
    Map<String, String> errors = const {},
  }) => _serial(() async {
    if (statuses.isEmpty) return;
    final pending = _read(_pendingKey);
    final remaining = <CapturedEvent>[];
    final settled = <CapturedEvent>[];
    for (final event in pending) {
      final state = statuses[event.eventId];
      if (state == null) {
        remaining.add(event);
      } else {
        settled.add(
          event.copyWith(
            deliveryState: state,
            error: errors[event.eventId],
          ),
        );
      }
    }
    final history = [...settled, ..._read(_historyKey)];
    await _write(_pendingKey, remaining);
    await _write(
      _historyKey,
      history.length > _maxHistory ? history.sublist(0, _maxHistory) : history,
    );
  });

  Future<void> clearHistory() => _serial(() => _write(_historyKey, const []));

  Future<void> clearAll() => _serial(() async {
    await _prefs.remove(_pendingKey);
    await _prefs.remove(_historyKey);
    await _prefs.remove(_sequenceKey);
  });

  Future<String> exportPreview() async => jsonEncode(
    (await pending(limit: 10)).map((event) => event.toJson()).toList(),
  );

  static String prettyTime(DateTime? value) {
    if (value == null) return 'Never';
    final local = value.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${local.year}-${two(local.month)}-${two(local.day)} '
        '${two(local.hour)}:${two(local.minute)}';
  }

  static String prettyShortTime(DateTime? value) {
    if (value == null) return 'Never';
    final local = value.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${prettyDay(value)}, ${two(local.hour)}:${two(local.minute)}';
  }

  static String prettyClock(DateTime? value) {
    if (value == null) return 'Never';
    final local = value.toLocal();
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(local.hour)}:${two(local.minute)}';
  }

  static String prettyDay(DateTime? value) {
    if (value == null) return 'No sync yet';
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ];
    final local = value.toLocal();
    return '${months[local.month - 1]} ${local.day}';
  }

  static String newEventId() => newUuidV4();
}

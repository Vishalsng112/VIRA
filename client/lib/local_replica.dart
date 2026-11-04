import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

class LocalReplica {
  LocalReplica._(this._preferences);

  final SharedPreferences _preferences;

  static Future<LocalReplica> open() async =>
      LocalReplica._(await SharedPreferences.getInstance());

  List<Map<String, dynamic>> readEntities(String householdId) {
    final raw = _preferences.getString('replica:$householdId:entities');
    if (raw == null) return [];
    final decoded = jsonDecode(raw);
    if (decoded is! List) return [];
    return decoded
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  Future<void> replaceEntities(
    String householdId,
    List<Map<String, dynamic>> entities,
  ) async {
    await _preferences.setString(
      'replica:$householdId:entities',
      jsonEncode(entities),
    );
  }

  List<Map<String, dynamic>> pendingOps(String householdId) {
    final raw = _preferences.getString('replica:$householdId:outbox');
    if (raw == null) return [];
    final decoded = jsonDecode(raw);
    if (decoded is! List) return [];
    return decoded
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  Future<void> enqueue(
    String householdId,
    Map<String, dynamic> operation,
  ) async {
    final operations = pendingOps(householdId)..add(operation);
    await _preferences.setString(
      'replica:$householdId:outbox',
      jsonEncode(operations),
    );
  }

  Future<void> removePending(
    String householdId,
    Set<String> operationIds,
  ) async {
    final operations = pendingOps(householdId)
        .where((operation) => !operationIds.contains(operation['op_id']))
        .toList();
    await _preferences.setString(
      'replica:$householdId:outbox',
      jsonEncode(operations),
    );
  }

  int cursor(String householdId) =>
      _preferences.getInt('replica:$householdId:cursor') ?? 0;

  Future<void> setCursor(String householdId, int value) async =>
      _preferences.setInt('replica:$householdId:cursor', value);

  Future<void> clearHousehold(String householdId) async {
    await _preferences.remove('replica:$householdId:entities');
    await _preferences.remove('replica:$householdId:outbox');
    await _preferences.remove('replica:$householdId:cursor');
  }
}

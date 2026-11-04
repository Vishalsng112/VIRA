import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'http_client.dart';
import 'local_replica.dart';

class ViraException implements Exception {
  ViraException(this.message, this.statusCode);
  final String message;
  final int statusCode;
  @override
  String toString() => message;
}

class ViraApi {
  ViraApi(String baseUrl)
    : baseUrl = _normalizeBaseUrl(baseUrl),
      _client = createHttpClient();
  final String baseUrl;
  final http.Client _client;
  static const _secureStorage = FlutterSecureStorage();
  String? _cookie;
  String? _deviceCredential;
  String? deviceId;
  String? householdId;
  LocalReplica? _replica;

  static String _normalizeBaseUrl(String value) {
    var normalized = value.trim();
    if (!normalized.contains('://')) {
      normalized = 'http://$normalized';
    }
    final uri = Uri.parse(normalized);
    if (uri.scheme == 'https' &&
        (uri.host == 'localhost' || uri.host == '127.0.0.1') &&
        (uri.port == 443 || uri.port == 8000)) {
      return uri
          .replace(scheme: 'http', port: uri.port == 443 ? 8000 : uri.port)
          .toString()
          .replaceFirst(RegExp(r'/$'), '');
    }
    return normalized.replaceFirst(RegExp(r'/$'), '');
  }

  Future<dynamic> _request(
    String method,
    String path, {
    Object? body,
    bool authenticated = true,
    String? idempotencyKey,
  }) async {
    final headers = <String, String>{
      'Content-Type': 'application/json',
      'X-Vira-Client': 'flutter/1.0.0 proto/1',
    };
    if (idempotencyKey != null) {
      headers['Idempotency-Key'] = idempotencyKey;
    }
    if (_cookie != null && authenticated) addCookieHeader(headers, _cookie!);
    final request = http.Request(method, Uri.parse('$baseUrl$path'))
      ..headers.addAll(headers);
    if (body != null) request.body = jsonEncode(body);
    final response = await _client.send(request);
    final text = await response.stream.bytesToString();
    // Browsers manage cookies themselves and intentionally hide Set-Cookie.
    // Native targets expose it, so retain it for the next authenticated call.
    final setCookie = response.headers['set-cookie'];
    if (setCookie != null) _cookie = setCookie.split(';').first;
    final decoded = text.isEmpty ? <String, dynamic>{} : jsonDecode(text);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded is Map ? decoded['detail'] : null;
      throw ViraException(
        detail?.toString() ?? 'Request failed',
        response.statusCode,
      );
    }

    return decoded;
  }

  Future<void> login(String username, String password) async {
    await _request(
      'POST',
      '/api/v1/auth/login',
      body: {'username': username, 'password': password},
      authenticated: false,
    );
    if (_cookie != null) {
      await _secureStorage.write(key: 'vira_session_cookie', value: _cookie);
    }

    await _secureStorage.write(key: 'vira_username', value: username);
  }

  Future<Map<String, dynamic>> setupServer(
    String username,
    String password,
    String confirmation,
  ) async => Map<String, dynamic>.from(
    await _request(
      'POST',
      '/api/v1/auth/setup',
      body: {
        'username': username,
        'password': password,
        'confirm_password': confirmation,
      },
      authenticated: false,
    ),
  );

  Future<void> resetPassword(
    String username,
    String recoveryCode,
    String password,
    String confirmation,
  ) async {
    await _request(
      'POST',
      '/api/v1/auth/password/reset',
      body: {
        'username': username,
        'recovery_code': recoveryCode,
        'new_password': password,
        'confirm_password': confirmation,
      },
      authenticated: false,
    );
  }

  Future<void> restoreSession() async {
    _cookie = await _secureStorage.read(key: 'vira_session_cookie');
    _deviceCredential = await _secureStorage.read(
      key: 'vira_device_credential',
    );
    deviceId = await _secureStorage.read(key: 'vira_device_id');
  }

  Future<String?> storedUsername() => _secureStorage.read(key: 'vira_username');

  Future<void> registerDevice({
    required String displayName,
    required String platform,
    required String deviceType,
  }) async {
    final result = Map<String, dynamic>.from(
      await _request(
        'POST',
        '/api/v1/devices',
        body: {
          'display_name': displayName,
          'platform': platform,
          'device_type': deviceType,
          'client_version': '1.0.0',
          'capabilities': ['family_sync', 'local_replica'],
        },
      ),
    );
    final credential = result['credential'];
    if (credential is Map && credential['token'] is String) {
      _deviceCredential = credential['token'] as String;
      await _secureStorage.write(
        key: 'vira_device_credential',
        value: _deviceCredential,
      );
    }
    deviceId = result['device_id']?.toString();
    if (deviceId != null) {
      await _secureStorage.write(key: 'vira_device_id', value: deviceId);
    }
  }

  Future<Map<String, dynamic>> currentUser() async =>
      Map<String, dynamic>.from(await _request('GET', '/api/v1/auth/me'));

  Future<Map<String, dynamic>> config() async => Map<String, dynamic>.from(
    await _request('GET', '/api/v1/client-config', authenticated: false),
  );

  Future<List<Map<String, dynamic>>> households() async {
    final result = Map<String, dynamic>.from(
      await _request('GET', '/api/v1/households'),
    );
    return (result['items'] as List)
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
  }

  Future<List<Map<String, dynamic>>> members(String id) async {
    final result = Map<String, dynamic>.from(
      await _request('GET', '/api/v1/households/$id/members'),
    );
    return (result['items'] as List)
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
  }

  Future<List<Map<String, dynamic>>> notebooks(String id) async {
    final result = Map<String, dynamic>.from(
      await _request('GET', '/api/v1/households/$id/notebooks'),
    );
    return (result['items'] as List)
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
  }

  Future<void> updateMember(
    String household,
    String member,
    String role,
  ) async {
    await _request(
      'PATCH',
      '/api/v1/households/$household/members/$member',
      body: {'role': role},
    );
  }

  Future<List<Map<String, dynamic>>> changes({int cursor = 0}) async {
    if (householdId == null) {
      throw StateError('Select a household before syncing');
    }
    final result = Map<String, dynamic>.from(
      await _request(
        'GET',
        '/api/v1/sync/changes?household_id=$householdId&cursor=$cursor',
      ),
    );
    return (result['changes'] as List)
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
  }

  Future<void> saveNote(
    String id,
    String title,
    String body, {
    String kind = 'note',
  }) async {
    if (householdId == null) {
      throw StateError('Select a household before saving');
    }
    await pushOps([
      {
        'op_id': id,
        'entity_type': 'note',
        'entity_id': id,
        'op': 'upsert',
        'base_version': 0,
        'data': {
          'id': id,
          'title': title,
          'body_md': body,
          'pinned': false,
          'kind': kind,
        },
      },
    ]);
  }

  Future<Map<String, dynamic>> pushOps(List<Map<String, dynamic>> ops) async {
    if (householdId == null) {
      throw StateError('Select a household before syncing');
    }

    final replica = _replica ??= await LocalReplica.open();
    await Future.wait(
      ops.map((operation) => replica.enqueue(householdId!, operation)),
    );
    try {
      final result = Map<String, dynamic>.from(
        await _request(
          'POST',
          '/api/v1/sync/push',
          body: {'household_id': householdId, 'ops': ops},
        ),
      );
      final results = (result['results'] as List? ?? [])
          .whereType<Map>()
          .where(
            (item) =>
                item['status'] == 'applied' || item['status'] == 'duplicate',
          )
          .map((item) => item['op_id']?.toString())
          .whereType<String>()
          .toSet();
      await replica.removePending(householdId!, results);
      return result;
    } catch (_) {
      rethrow;
    }
  }

  Future<int> pendingOperationCount() async {
    if (householdId == null) return 0;
    final replica = _replica ??= await LocalReplica.open();
    return replica.pendingOps(householdId!).length;
  }

  Future<void> flushPendingOps() async {
    if (householdId == null) return;
    final replica = _replica ??= await LocalReplica.open();
    final pending = replica.pendingOps(householdId!);
    if (pending.isNotEmpty) await pushOps(pending);
  }

  Future<void> saveChecklistItem({
    required String id,
    required String noteId,
    required String text,
    required bool done,
  }) async => pushOps([
    {
      'op_id': id,
      'entity_type': 'checklist_item',
      'entity_id': id,
      'op': 'upsert',
      'base_version': 0,
      'data': {
        'id': id,
        'note_id': noteId,
        'text': text,
        'done': done,
        'position': 'a0',
      },
    },
  ]);

  Future<void> saveReminder({
    required String id,
    required String title,
    required String dueAt,
    bool urgent = false,
  }) async => pushOps([
    {
      'op_id': id,
      'entity_type': 'reminder',
      'entity_id': id,
      'op': 'upsert',
      'base_version': 0,
      'data': {
        'id': id,
        'title': title,
        'due_at': dueAt,
        'urgent': urgent,
        'status': 'active',
      },
    },
  ]);

  Future<Map<String, dynamic>> chat(String message) async {
    final idempotencyKey =
        'flutter-${DateTime.now().toUtc().microsecondsSinceEpoch}-${message.hashCode}';
    final result = await _request(
      'POST',
      '/chat',
      body: {'message': message},
      idempotencyKey: idempotencyKey,
    );
    return Map<String, dynamic>.from(result as Map);
  }

  Future<Map<String, dynamic>> orchestration() async =>
      Map<String, dynamic>.from(await _request('GET', '/orchestration'));

  Future<Map<String, dynamic>> health() async =>
      Map<String, dynamic>.from(await _request('GET', '/health'));

  Future<Map<String, dynamic>> agents() async =>
      Map<String, dynamic>.from(await _request('GET', '/agents'));

  Future<Map<String, dynamic>> workspace() async =>
      Map<String, dynamic>.from(await _request('GET', '/api/v1/workspace'));

  Future<List<Map<String, dynamic>>> devices() async {
    final result = Map<String, dynamic>.from(
      await _request('GET', '/api/v1/devices'),
    );
    final items = result['devices'] ?? result['items'] ?? [];
    return (items as List)
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
  }

  Future<void> renameDevice(String id, String displayName) async {
    await _request(
      'PATCH',
      '/api/v1/devices/$id',
      body: {'display_name': displayName},
    );
  }

  Future<void> revokeDevice(String id) async {
    await _request('POST', '/api/v1/devices/$id/revoke');
  }

  Future<List<Map<String, dynamic>>> users() async {
    final result = Map<String, dynamic>.from(
      await _request('GET', '/api/v1/admin/users'),
    );
    return (result['users'] as List? ?? [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();
  }

  Future<Map<String, dynamic>> createUser({
    required String username,
    required String role,
    String? password,
  }) async {
    final result = await _request(
      'POST',
      '/api/v1/admin/users',
      body: {
        'username': username,
        'role': role,
        if (password != null && password.isNotEmpty) 'password': password,
      },
    );
    return Map<String, dynamic>.from(result as Map);
  }

  Future<void> updateUser(String userId, {String? role, String? status}) async {
    final body = <String, dynamic>{};
    if (role != null) body['role'] = role;
    if (status != null) body['status'] = status;
    await _request('PATCH', '/api/v1/admin/users/$userId', body: body);
  }

  Future<void> logout() async {
    await _request('POST', '/api/v1/auth/logout', authenticated: false);
    _cookie = null;
    _deviceCredential = null;
    await _secureStorage.delete(key: 'vira_session_cookie');
    await _secureStorage.delete(key: 'vira_device_credential');
    await _secureStorage.delete(key: 'vira_device_id');
    await _secureStorage.delete(key: 'vira_username');
  }
}

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../core/models/captured_event.dart';
import '../../core/models/device_info.dart';

class ViraApiException implements Exception {
  ViraApiException(
    this.statusCode,
    this.code,
    this.message, {
    this.retryAfter,
  });

  final int statusCode;
  final String code;
  final String message;
  final Duration? retryAfter;

  bool get isAuthFailure => statusCode == 401 || code == 'device_revoked';
  bool get isTransport => statusCode == 0;
  bool get isRetryable =>
      isTransport || statusCode == 408 || statusCode == 429 || statusCode >= 500;

  @override
  String toString() => message;
}

class BatchResult {
  const BatchResult({
    required this.statuses,
    required this.errors,
    this.correlationId,
  });

  final Map<String, EventDeliveryState> statuses;
  final Map<String, String> errors;
  final String? correlationId;
}

class ViraApi {
  ViraApi(
    String baseUrl, {
    http.Client? client,
    this.clientVersion = '1.0.0',
  }) : baseUrl = normalizeBaseUrl(baseUrl),
       _client = client ?? http.Client();

  static const protocolVersion = 1;

  final String baseUrl;
  final String clientVersion;
  final http.Client _client;

  String? sessionId;
  String? deviceId;
  String? deviceToken;

  static String normalizeBaseUrl(String value) {
    var normalized = value.trim();
    if (normalized.isEmpty) return normalized;
    if (!normalized.contains('://')) normalized = 'http://$normalized';
    final uri = Uri.parse(normalized);
    final cleaned = uri.replace(
      path: uri.path.replaceFirst(RegExp(r'/+$'), ''),
    );
    return cleaned.toString().replaceFirst(RegExp(r'/$'), '');
  }

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Map<String, String> _headers({bool user = false, bool device = false}) => {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    'X-Vira-Client': 'vira-link/$clientVersion proto/$protocolVersion',
    if (user && sessionId != null) 'Authorization': 'Bearer $sessionId',
    if (device && deviceToken != null) 'Authorization': 'Bearer $deviceToken',
  };

  Future<Map<String, dynamic>> _decode(http.Response response) async {
    final raw = response.body;
    Map<String, dynamic> body = const {};
    if (raw.trim().isNotEmpty) {
      try {
        final decoded = jsonDecode(raw);
        if (decoded is Map) body = Map<String, dynamic>.from(decoded);
      } on FormatException {
        // Fall through to a status-based error below.
      }
    }
    if (response.statusCode >= 200 && response.statusCode < 300) return body;

    final error = body['error'];
    final code = error is Map ? error['code']?.toString() : null;
    final detail = body['detail']?.toString() ?? error?.toString();
    final retryAfter = int.tryParse(response.headers['retry-after'] ?? '');
    throw ViraApiException(
      response.statusCode,
      code ?? _fallbackCode(response.statusCode),
      detail?.isNotEmpty == true ? detail! : _fallbackMessage(response.statusCode),
      retryAfter: retryAfter == null ? null : Duration(seconds: retryAfter),
    );
  }

  Future<http.Response> _send(
    String method,
    String path, {
    Map<String, dynamic>? body,
    bool user = false,
    bool device = false,
    Duration timeout = const Duration(seconds: 25),
  }) async {
    final request = http.Request(method, _uri(path))
      ..headers.addAll(_headers(user: user, device: device));
    if (body != null) request.body = jsonEncode(body);
    try {
      final streamed = await _client.send(request).timeout(timeout);
      return await http.Response.fromStream(streamed);
    } on TimeoutException {
      throw ViraApiException(
        0,
        'timeout',
        'The VIRA server did not respond in time. Events stay queued.',
      );
    } on Object {
      throw ViraApiException(
        0,
        'network_error',
        'Cannot reach the VIRA server. Check the address and network.',
      );
    }
  }

  Future<Map<String, dynamic>> login(String username, String password) async {
    final response = await _send(
      'POST',
      '/api/v1/auth/login',
      body: {'username': username.trim(), 'password': password},
    );
    final body = await _decode(response);
    final principal = body['principal'];
    if (principal is Map && principal['session_id'] is String) {
      sessionId = principal['session_id'] as String;
    }
    return body;
  }

  Future<Map<String, dynamic>> setupAdministrator(
    String username,
    String password,
    String confirmation,
  ) async {
    final response = await _send(
      'POST',
      '/api/v1/auth/setup',
      body: {
        'username': username.trim(),
        'password': password,
        'confirm_password': confirmation,
      },
    );
    return _decode(response);
  }

  Future<void> logout() async {
    try {
      await _send('POST', '/api/v1/auth/logout', user: true);
    } on ViraApiException {
      // Sessions also expire server-side; logout is best effort.
    }
    sessionId = null;
  }

  Future<Map<String, dynamic>> me() async =>
      _decode(await _send('GET', '/api/v1/auth/me', user: true));

  Future<Map<String, dynamic>> clientConfig() async =>
      _decode(await _send('GET', '/api/v1/client-config'));

  Future<(DeviceInfo, String)> registerDevice({
    required String displayName,
    required DeviceProfile profile,
    required List<String> capabilities,
  }) async {
    final response = await _send(
      'POST',
      '/api/v1/devices',
      user: true,
      body: {
        'display_name': displayName.trim(),
        'platform': profile.platform,
        'device_type': profile.deviceType,
        'os_version': profile.osVersion,
        'client_version': clientVersion,
        'capabilities': capabilities,
      },
    );
    final body = await _decode(response);
    deviceId = body['device_id']?.toString();
    final credential = body['credential'];
    if (credential is! Map || credential['token'] is! String) {
      throw ViraApiException(
        response.statusCode,
        'invalid_registration',
        'The server did not return a device credential.',
      );
    }
    deviceToken = credential['token'] as String;
    return (DeviceInfo.fromJson(body), deviceToken!);
  }

  Future<Map<String, dynamic>> heartbeat({
    required DeviceProfile profile,
    required List<String> capabilities,
    required Map<String, String> capabilityStatus,
    required int queueBacklog,
  }) async {
    if (deviceId == null) {
      throw ViraApiException(0, 'not_enrolled', 'This device is not enrolled.');
    }
    final response = await _send(
      'POST',
      '/api/v1/devices/$deviceId/heartbeat',
      device: true,
      body: {
        'client_version': clientVersion,
        'os_version': profile.osVersion,
        'capabilities': capabilities,
        'capability_status': capabilityStatus,
        'queue_backlog': queueBacklog,
      },
    );
    return _decode(response);
  }

  Future<BatchResult> sendEvents(List<CapturedEvent> events) async {
    if (deviceId == null) {
      throw ViraApiException(0, 'not_enrolled', 'This device is not enrolled.');
    }
    final response = await _send(
      'POST',
      '/api/v1/devices/$deviceId/events:batch',
      device: true,
      body: {'events': events.map((event) => event.toIngestJson()).toList()},
    );
    final body = await _decode(response);
    final statuses = <String, EventDeliveryState>{};
    final errors = <String, String>{};
    for (final item in (body['results'] as List? ?? const []).whereType<Map>()) {
      final id = item['event_id']?.toString();
      if (id == null) continue;
      final status = item['status']?.toString();
      if (status == 'accepted' || status == 'duplicate') {
        statuses[id] = EventDeliveryState.sent;
      } else if (status == 'rejected') {
        statuses[id] = EventDeliveryState.rejected;
        final message = item['message']?.toString() ?? 'Rejected by the server';
        final code = item['code']?.toString();
        errors[id] = code == null ? message : '$message ($code)';
      }
    }
    return BatchResult(
      statuses: statuses,
      errors: errors,
      correlationId: body['correlation_id']?.toString(),
    );
  }

  Future<List<DeviceInfo>> devices() async {
    final body = await _decode(await _send('GET', '/api/v1/devices', user: true));
    return ((body['devices'] as List?) ?? const [])
        .whereType<Map>()
        .map((item) => DeviceInfo.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<void> renameDevice(String id, String displayName) async {
    await _decode(
      await _send(
        'PATCH',
        '/api/v1/devices/$id',
        user: true,
        body: {'display_name': displayName.trim()},
      ),
    );
  }

  Future<void> revokeDevice(String id) async {
    await _decode(await _send('POST', '/api/v1/devices/$id/revoke', user: true));
  }

  Future<void> retireDevice(String id) async {
    await _decode(await _send('POST', '/api/v1/devices/$id/retire', user: true));
  }

  Future<Map<String, dynamic>> deviceState(String id) async =>
      _decode(await _send('GET', '/api/v1/devices/$id/state', user: true));

  void close() => _client.close();

  static String _fallbackCode(int status) => switch (status) {
    400 => 'bad_request',
    401 => 'unauthorized',
    403 => 'forbidden',
    404 => 'not_found',
    409 => 'conflict',
    422 => 'validation_failed',
    429 => 'rate_limited',
    _ => 'http_error',
  };

  static String _fallbackMessage(int status) => switch (status) {
    401 => 'Your session is no longer valid. Sign in again.',
    403 => 'This device is not allowed to perform that action.',
    429 => 'The server is rate limiting this device. Retrying shortly.',
    >= 500 => 'The VIRA server returned an error. It will be retried.',
    _ => 'Request failed ($status).',
  };
}

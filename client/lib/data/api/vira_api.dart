import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../core/config/app_config.dart';
import '../../core/models/captured_event.dart';
import '../../core/models/chat_models.dart';
import '../../core/models/device_info.dart';
import '../../core/models/pairing_code.dart';
import '../../core/models/agent_inbox.dart';
import '../../core/utils/ids.dart';

class ViraApiException implements Exception {
  ViraApiException(this.statusCode, this.code, this.message, {this.retryAfter});

  final int statusCode;
  final String code;
  final String message;
  final Duration? retryAfter;

  bool get isAuthFailure => statusCode == 401 || code == 'device_revoked';
  bool get isTransport => statusCode == 0;
  bool get isRetryable =>
      isTransport ||
      statusCode == 408 ||
      statusCode == 429 ||
      statusCode >= 500;

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
    this.clientVersion = appVersion,
    List<String>? endpoints,
  }) : _client = client ?? http.Client(),
       _endpoints = _normalizeEndpoints(baseUrl, endpoints) {
    this.baseUrl = _endpoints.first;
  }

  static const protocolVersion = 1;

  late String baseUrl;
  final String clientVersion;
  final http.Client _client;
  final List<String> _endpoints;

  List<String> get endpoints => List.unmodifiable(_endpoints);

  static List<String> _normalizeEndpoints(String primary, List<String>? extra) {
    final result = <String>[];
    for (final value in [primary, ...?extra]) {
      final normalized = normalizeBaseUrl(value);
      if (normalized.isNotEmpty && !result.contains(normalized)) {
        result.add(normalized);
      }
    }
    if (result.isEmpty) result.add(normalizeBaseUrl(primary));
    return result;
  }

  List<String> _attemptOrder() {
    final result = <String>[];
    if (baseUrl.isNotEmpty) result.add(baseUrl);
    for (final endpoint in _endpoints) {
      if (!result.contains(endpoint)) result.add(endpoint);
    }
    return result;
  }

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
      detail?.isNotEmpty == true
          ? detail!
          : _fallbackMessage(response.statusCode),
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
    final candidates = _attemptOrder();
    ViraApiException? lastError;
    for (var index = 0; index < candidates.length; index++) {
      final endpoint = candidates[index];
      final isLast = index == candidates.length - 1;
      final attemptTimeout = isLast || timeout <= const Duration(seconds: 8)
          ? timeout
          : const Duration(seconds: 8);
      baseUrl = endpoint;
      final request = http.Request(method, _uri(path))
        ..headers.addAll(_headers(user: user, device: device));
      if (body != null) request.body = jsonEncode(body);
      try {
        final streamed = await _client.send(request).timeout(attemptTimeout);
        return await http.Response.fromStream(streamed);
      } on TimeoutException {
        lastError = ViraApiException(
          0,
          'timeout',
          isLast
              ? 'The VIRA server did not respond in time. Events stay queued.'
              : 'A server address timed out; trying the next address.',
        );
      } on Object {
        lastError = ViraApiException(
          0,
          'network_error',
          isLast
              ? 'Cannot reach the VIRA server. Tried ${candidates.join(", ")}.'
              : 'A server address is unreachable; trying the next address.',
        );
      }
    }
    throw lastError ??
        ViraApiException(
          0,
          'network_error',
          'Cannot reach the VIRA server. Check the address and network.',
        );
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

  /// Safe workspace status available to every signed-in user.
  Future<Map<String, dynamic>> workspace() async =>
      _decode(await _send('GET', '/api/v1/workspace', user: true));

  // ---------------------------------------------------------------------------
  // Chat (the server's Chatbot agent)
  // ---------------------------------------------------------------------------

  Future<List<ChatConversation>> conversations({int limit = 50}) async {
    final body = await _decode(
      await _send('GET', '/api/v1/conversations?limit=$limit', user: true),
    );
    return ((body['conversations'] as List?) ?? const [])
        .whereType<Map>()
        .map(
          (item) => ChatConversation.fromJson(Map<String, dynamic>.from(item)),
        )
        .where((item) => item.id.isNotEmpty)
        .toList();
  }

  Future<ChatConversation> createConversation({
    String title = 'New chat',
    bool incognito = false,
  }) async {
    final body = await _decode(
      await _send(
        'POST',
        '/api/v1/conversations',
        user: true,
        body: {'title': title, 'incognito': incognito},
      ),
    );
    return ChatConversation.fromJson(body);
  }

  Future<List<ChatMessage>> conversationMessages(
    String conversationId, {
    int limit = 100,
  }) async {
    final body = await _decode(
      await _send(
        'GET',
        '/api/v1/conversations/$conversationId/messages?limit=$limit',
        user: true,
      ),
    );
    return ((body['messages'] as List?) ?? const [])
        .whereType<Map>()
        .map((item) => ChatMessage.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<void> renameConversation(String id, String title) async {
    await _decode(
      await _send(
        'PATCH',
        '/api/v1/conversations/$id',
        user: true,
        body: {'title': title},
      ),
    );
  }

  Future<void> deleteConversation(String id) async {
    await _decode(
      await _send('DELETE', '/api/v1/conversations/$id', user: true),
    );
  }

  /// Streams the agent's progress as NDJSON events.
  ///
  /// Every event is a [ChatStreamEvent]; the final one is `type == 'done'`
  /// (with the answer) or `type == 'error'`. The server requires an
  /// `Idempotency-Key`, so retries never duplicate a message.
  Stream<ChatStreamEvent> streamChat({
    required String message,
    String? conversationId,
    String? agentId,
    String? deviceId,
    String? idempotencyKey,
  }) async* {
    final request = http.Request('POST', _uri('/chat/stream'))
      ..headers.addAll({
        ..._headers(user: true),
        'Accept': 'application/x-ndjson',
        'Idempotency-Key': idempotencyKey ?? newUuidV4(),
      });
    request.body = jsonEncode({
      'message': message,
      'conversation_id': ?conversationId,
      'agent_id': ?agentId,
      'device_id': ?deviceId,
    });

    http.StreamedResponse response;
    try {
      response = await _client
          .send(request)
          .timeout(const Duration(seconds: 45));
    } on TimeoutException {
      throw ViraApiException(
        0,
        'timeout',
        'The VIRA server did not respond in time.',
      );
    } on Object {
      throw ViraApiException(
        0,
        'network_error',
        'Cannot reach the VIRA server. Check the address and network.',
      );
    }

    if (response.statusCode < 200 || response.statusCode >= 300) {
      final raw = await response.stream.bytesToString();
      Map<String, dynamic> body = const {};
      try {
        final decoded = jsonDecode(raw);
        if (decoded is Map) body = Map<String, dynamic>.from(decoded);
      } on FormatException {
        // Fall back to the status code below.
      }
      final error = body['error'];
      final code = error is Map ? error['code']?.toString() : null;
      final detail = body['detail']?.toString() ?? error?.toString();
      throw ViraApiException(
        response.statusCode,
        code ?? _fallbackCode(response.statusCode),
        detail?.isNotEmpty == true
            ? detail!
            : _fallbackMessage(response.statusCode),
      );
    }

    final lines = response.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter());
    await for (final line in lines) {
      final trimmed = line.trim();
      if (trimmed.isEmpty) continue;
      Map<String, dynamic> data;
      try {
        final decoded = jsonDecode(trimmed);
        if (decoded is! Map) continue;
        data = Map<String, dynamic>.from(decoded);
      } on FormatException {
        continue;
      }
      yield ChatStreamEvent((data['type'] ?? 'status').toString(), data);
    }
  }

  Stream<AgentNotification> streamNotifications() async* {
    final request = http.Request('GET', _uri('/api/v1/notifications/stream'))
      ..headers.addAll({
        ..._headers(user: true),
        'Accept': 'application/x-ndjson',
      });
    http.StreamedResponse response;
    try {
      response = await _client
          .send(request)
          .timeout(const Duration(seconds: 30));
    } on TimeoutException {
      throw ViraApiException(0, 'timeout', 'Notification stream timed out.');
    } on Object {
      throw ViraApiException(
        0,
        'network_error',
        'Cannot reach the VIRA notification stream.',
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ViraApiException(
        response.statusCode,
        _fallbackCode(response.statusCode),
        _fallbackMessage(response.statusCode),
      );
    }
    final lines = response.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter());
    await for (final line in lines) {
      final trimmed = line.trim();
      if (trimmed.isEmpty) continue;
      Map<String, dynamic> data;
      try {
        final decoded = jsonDecode(trimmed);
        if (decoded is! Map) continue;
        data = Map<String, dynamic>.from(decoded);
      } on FormatException {
        continue;
      }
      if (data['type'] != 'notification') continue;
      final item = data['notification'];
      if (item is Map) {
        yield AgentNotification.fromJson(Map<String, dynamic>.from(item));
      }
    }
  }

  Future<(DeviceInfo, String)> registerDevice({
    required String displayName,
    required DeviceProfile profile,
    required List<String> capabilities,
    required String installationId,
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
        'installation_id': installationId,
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

  /// Redeems a short-lived pairing code. This is unauthenticated on the wire;
  /// the code itself authorizes the enrollment and issues a user session.
  Future<PairingResult> pairDevice({
    required String code,
    required String displayName,
    required DeviceProfile profile,
    required List<String> capabilities,
    required String installationId,
  }) async {
    final response = await _send(
      'POST',
      '/api/v1/devices/pair',
      body: {
        'code': PairingPayload.normalizeCode(code) ?? code.trim().toUpperCase(),
        'display_name': displayName.trim(),
        'platform': profile.platform,
        'device_type': profile.deviceType,
        'os_version': profile.osVersion,
        'client_version': clientVersion,
        'capabilities': capabilities,
        'installation_id': installationId,
      },
    );
    final body = await _decode(response);
    deviceId = body['device_id']?.toString();
    final credential = body['credential'];
    if (credential is! Map || credential['token'] is! String) {
      throw ViraApiException(
        response.statusCode,
        'invalid_pairing',
        'The server did not return a device credential.',
      );
    }
    deviceToken = credential['token'] as String;
    final sessionId = body['session_id']?.toString();
    this.sessionId = sessionId;
    final account = body['account'];
    final roles = account is Map && account['roles'] is List
        ? (account['roles'] as List).map((role) => role.toString()).toList()
        : const <String>[];
    return PairingResult(
      device: DeviceInfo.fromJson(body),
      token: deviceToken!,
      sessionId: sessionId,
      username: account is Map ? account['username']?.toString() : null,
      roles: roles,
    );
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
    for (final item
        in (body['results'] as List? ?? const []).whereType<Map>()) {
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
    final body = await _decode(
      await _send('GET', '/api/v1/devices', user: true),
    );
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
    await _decode(
      await _send('POST', '/api/v1/devices/$id/revoke', user: true),
    );
  }

  Future<void> retireDevice(String id) async {
    await _decode(
      await _send('POST', '/api/v1/devices/$id/retire', user: true),
    );
  }

  Future<Map<String, dynamic>> deviceState(String id) async =>
      _decode(await _send('GET', '/api/v1/devices/$id/state', user: true));

  Future<List<Map<String, dynamic>>> pendingCommands() async {
    if (deviceId == null) return const [];
    final body = await _decode(
      await _send(
        'GET',
        '/api/v1/devices/$deviceId/commands/pending',
        device: true,
      ),
    );
    return ((body['commands'] as List?) ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  Future<void> completeCommand(
    String id, {
    String status = 'completed',
    Object? result,
  }) async {
    if (deviceId == null) return;
    await _decode(
      await _send(
        'POST',
        '/api/v1/devices/$deviceId/commands/$id/result',
        device: true,
        body: {'status': status, 'result': result},
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Agent inbox: proactive outputs and schedules
  // ---------------------------------------------------------------------------

  Future<List<AgentNotification>> notifications({
    int limit = 100,
    bool unreadOnly = false,
  }) async {
    final query = 'limit=$limit${unreadOnly ? '&unread_only=true' : ''}';
    final body = await _decode(
      await _send('GET', '/api/v1/notifications?$query', user: true),
    );
    return ((body['notifications'] as List?) ?? const [])
        .whereType<Map>()
        .map(
          (item) => AgentNotification.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList();
  }

  Future<int> unreadNotificationCount() async {
    final body = await _decode(
      await _send('GET', '/api/v1/notifications/unread-count', user: true),
    );
    return (body['unread'] as num?)?.toInt() ?? 0;
  }

  Future<void> markNotificationRead(String id) async {
    await _decode(
      await _send('POST', '/api/v1/notifications/$id/read', user: true),
    );
  }

  Future<List<AgentSchedule>> agentSchedules() async {
    final body = await _decode(
      await _send('GET', '/api/v1/agent-schedules', user: true),
    );
    return ((body['schedules'] as List?) ?? const [])
        .whereType<Map>()
        .map((item) => AgentSchedule.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<List<AgentRecipe>> agentRecipes() async {
    final body = await _decode(
      await _send('GET', '/api/v1/agent-recipes', user: true),
    );
    return ((body['agents'] as List?) ?? const [])
        .whereType<Map>()
        .map((item) => AgentRecipe.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<AgentSchedule> createAgentSchedule({
    required String agentId,
    required String name,
    required String message,
    required String scheduleType,
    required String timezone,
    String? timeOfDay,
    int? weekday,
    int? intervalMinutes,
    String? quietHoursStart,
    String? quietHoursEnd,
    List<String> channels = const ['inapp'],
    Map<String, dynamic> input = const {},
    bool enabled = true,
  }) async {
    final body = await _decode(
      await _send(
        'POST',
        '/api/v1/agent-schedules',
        user: true,
        body: {
          'agent_id': agentId,
          'name': name,
          'message': message,
          'schedule_type': scheduleType,
          'timezone': timezone,
          'channels': channels,
          'input': input,
          'enabled': enabled,
          'time_of_day': ?timeOfDay,
          'weekday': ?weekday,
          'interval_minutes': ?intervalMinutes,
          'quiet_hours_start': ?quietHoursStart,
          'quiet_hours_end': ?quietHoursEnd,
        },
      ),
    );
    return AgentSchedule.fromJson(body);
  }

  Future<AgentSchedule> updateAgentSchedule(
    String scheduleId,
    Map<String, dynamic> changes,
  ) async {
    final body = await _decode(
      await _send(
        'PATCH',
        '/api/v1/agent-schedules/$scheduleId',
        user: true,
        body: changes,
      ),
    );
    return AgentSchedule.fromJson(body);
  }

  Future<void> deleteAgentSchedule(String scheduleId) async {
    await _decode(
      await _send('DELETE', '/api/v1/agent-schedules/$scheduleId', user: true),
    );
  }

  Future<void> runAgentSchedule(String scheduleId) async {
    await _decode(
      await _send(
        'POST',
        '/api/v1/agent-schedules/$scheduleId/run',
        user: true,
      ),
    );
  }

  Future<List<AgentScheduleRun>> agentScheduleRuns(
    String scheduleId, {
    int limit = 50,
  }) async {
    final body = await _decode(
      await _send(
        'GET',
        '/api/v1/agent-schedules/$scheduleId/runs?limit=$limit',
        user: true,
      ),
    );
    return ((body['runs'] as List?) ?? const [])
        .whereType<Map>()
        .map(
          (item) => AgentScheduleRun.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList();
  }

  Future<AgentScheduleRunDetail> agentScheduleRun(
    String scheduleId,
    String runId,
  ) async {
    final body = await _decode(
      await _send(
        'GET',
        '/api/v1/agent-schedules/$scheduleId/runs/$runId',
        user: true,
      ),
    );
    return AgentScheduleRunDetail.fromJson(body);
  }

  Future<void> registerPushToken({
    required String platform,
    required String token,
  }) async {
    if (deviceId == null) {
      throw ViraApiException(0, 'not_enrolled', 'This device is not enrolled.');
    }
    await _decode(
      await _send(
        'POST',
        '/api/v1/devices/$deviceId/push-registration',
        device: true,
        body: {'platform': platform, 'token': token},
      ),
    );
  }

  Future<Map<String, dynamic>> health() async =>
      _decode(await _send('GET', '/health', user: true));
  Future<Map<String, dynamic>> metrics() async =>
      _decode(await _send('GET', '/metrics', user: true));

  Future<Map<String, dynamic>> orchestration() async =>
      _decode(await _send('GET', '/orchestration', user: true));

  Future<Map<String, dynamic>> agents() async =>
      _decode(await _send('GET', '/agents', user: true));

  Future<void> setAgentEnabled(String id, bool enabled) async {
    await _decode(
      await _send(
        'PATCH',
        '/agents/$id',
        user: true,
        body: {'enabled': enabled},
      ),
    );
  }

  Future<void> unregisterAgent(String id) async {
    await _decode(await _send('DELETE', '/agents/$id', user: true));
  }

  Future<List<Map<String, dynamic>>> adminUsers({
    bool includeDeleted = false,
  }) async {
    final body = await _decode(
      await _send(
        'GET',
        '/api/v1/admin/users?include_deleted=$includeDeleted',
        user: true,
      ),
    );
    return ((body['users'] as List?) ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  Future<Map<String, dynamic>> createAdminUser({
    required String username,
    required String role,
    String? password,
  }) async => _decode(
    await _send(
      'POST',
      '/api/v1/admin/users',
      user: true,
      body: {
        'username': username,
        'role': role,
        if (password != null && password.isNotEmpty) 'password': password,
      },
    ),
  );

  Future<Map<String, dynamic>> updateAdminUser(
    String id, {
    String? role,
    String? status,
  }) async => _decode(
    await _send(
      'PATCH',
      '/api/v1/admin/users/$id',
      user: true,
      body: {'role': ?role, 'status': ?status},
    ),
  );

  Future<void> deleteAdminUser(String id) async {
    await _decode(await _send('DELETE', '/api/v1/admin/users/$id', user: true));
  }

  Future<Map<String, dynamic>> adminDevices() async =>
      _decode(await _send('GET', '/api/v1/admin/devices', user: true));

  Future<Map<String, dynamic>> auditLog() async =>
      _decode(await _send('GET', '/api/v1/admin/audit', user: true));

  /// Opt-in, already-redacted client diagnostic report.
  Future<Map<String, dynamic>> submitDiagnostics(
    Map<String, dynamic> report,
  ) async => _decode(
    await _send('POST', '/api/v1/diagnostics', user: true, body: report),
  );

  Future<Map<String, dynamic>> insightFleet() async =>
      _decode(await _send('GET', '/api/v1/insights/fleet', user: true));

  Future<Map<String, dynamic>> sensors() async =>
      _decode(await _send('GET', '/ops/sensors', user: true));

  Future<Map<String, dynamic>> eventLag() async =>
      _decode(await _send('GET', '/ops/events/lag', user: true));

  Future<Map<String, dynamic>> modules() async =>
      _decode(await _send('GET', '/modules', user: true));

  Future<Map<String, dynamic>> adminJobs({String? status}) async => _decode(
    await _send(
      'GET',
      '/api/v1/admin/jobs${status == null ? '' : '?status=$status'}',
      user: true,
    ),
  );

  Future<void> retryJob(String id) async {
    await _decode(
      await _send('POST', '/api/v1/admin/jobs/$id/retry', user: true),
    );
  }

  Future<Map<String, dynamic>> adminBackups() async =>
      _decode(await _send('GET', '/api/v1/admin/backups', user: true));

  Future<Map<String, dynamic>> createBackup() async =>
      _decode(await _send('POST', '/api/v1/admin/backups', user: true));

  Future<Map<String, dynamic>> alerts() async {
    try {
      return await _decode(
        await _send('GET', '/api/v1/ops/alerts', user: true),
      );
    } on ViraApiException catch (error) {
      // Older servers exposed this route without the /api/v1 prefix.
      if (error.statusCode != 404) rethrow;
    }
    return _decode(await _send('GET', '/ops/alerts', user: true));
  }

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

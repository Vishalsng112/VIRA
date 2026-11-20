import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vira_link/core/models/captured_event.dart';
import 'package:vira_link/core/models/chat_models.dart';
import 'package:vira_link/core/models/device_info.dart';
import 'package:vira_link/data/api/vira_api.dart';

void main() {
  test('enroll, heartbeat and ingest follow the device API contract', () async {
    final seen = <String, http.Request>{};
    final client = MockClient((request) async {
      seen['${request.method} ${request.url.path}'] = request;
      if (request.url.path == '/api/v1/auth/login') {
        return http.Response(
          jsonEncode({
            'status': 'success',
            'principal': {
              'user_id': 1,
              'username': 'alice',
              'roles': ['admin'],
              'session_id': 'session-123',
            },
          }),
          200,
        );
      }
      if (request.url.path == '/api/v1/devices') {
        expect(request.headers['Authorization'], 'Bearer session-123');
        return http.Response(
          jsonEncode({
            'device_id': 'device-1',
            'display_name': 'Test laptop',
            'platform': 'linux',
            'device_type': 'desktop',
            'status': 'pending',
            'capabilities': ['device_status'],
            'credential': {
              'token': 'vdc_token',
              'scopes': ['events:write'],
            },
          }),
          201,
        );
      }
      if (request.url.path.endsWith('/heartbeat')) {
        expect(request.headers['Authorization'], 'Bearer vdc_token');
        return http.Response(
          jsonEncode({'device_id': 'device-1', 'status': 'active'}),
          200,
        );
      }
      if (request.url.path.endsWith('/events:batch')) {
        expect(request.headers['Authorization'], 'Bearer vdc_token');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        final events = body['events'] as List;
        return http.Response(
          jsonEncode({
            'accepted': events.length,
            'duplicates': 0,
            'rejected': 0,
            'results': [
              for (final event in events)
                {'event_id': event['event_id'], 'status': 'accepted'},
            ],
          }),
          200,
        );
      }
      return http.Response('{}', 404);
    });

    final api = ViraApi('http://localhost:8000/', client: client);
    await api.login('alice', 'secret');
    expect(api.sessionId, 'session-123');

    final (device, token) = await api.registerDevice(
      displayName: 'Test laptop',
      profile: const DeviceProfile(
        platform: 'linux',
        deviceType: 'desktop',
        osVersion: 'Linux 6',
        hostname: 'test',
      ),
      capabilities: ['device_status'],
      installationId: 'install-abc',
    );
    expect(
      (jsonDecode(seen['POST /api/v1/devices']!.body)
          as Map)['installation_id'],
      'install-abc',
    );
    expect(device.deviceId, 'device-1');
    expect(token, 'vdc_token');

    await api.heartbeat(
      profile: const DeviceProfile(
        platform: 'linux',
        deviceType: 'desktop',
        osVersion: 'Linux 6',
        hostname: 'test',
      ),
      capabilities: ['device_status'],
      capabilityStatus: {'device_status': 'available'},
      queueBacklog: 1,
    );

    final event = CapturedEvent(
      eventId: '3d0f2d3a-4f6a-4b7c-8f7e-0123456789ab',
      type: 'device.telemetry.test',
      occurredAt: DateTime.utc(2026, 1, 1),
      sourceComponent: 'vira_link',
      payload: const {'message': 'hello'},
      deviceSequence: 1,
    );
    final result = await api.sendEvents([event]);
    expect(result.statuses[event.eventId], EventDeliveryState.sent);
    expect(seen.keys, contains('POST /api/v1/devices/device-1/events:batch'));
  });

  test('maps rejected events without throwing the whole batch', () async {
    final client = MockClient(
      (request) async => http.Response(
        jsonEncode({
          'results': [
            {
              'event_id': 'evt-1',
              'status': 'rejected',
              'code': 'type_not_allowed',
              'message': 'Event type is not permitted for devices',
            },
          ],
        }),
        200,
      ),
    );
    final api = ViraApi('http://localhost:8000', client: client)
      ..deviceId = 'device-1'
      ..deviceToken = 'vdc_token';
    final result = await api.sendEvents([
      CapturedEvent(
        eventId: 'evt-1',
        type: 'sensor.unknown.state',
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: 'test',
        payload: const {},
      ),
    ]);
    expect(result.statuses['evt-1'], EventDeliveryState.rejected);
    expect(result.errors['evt-1'], contains('type_not_allowed'));
  });

  test('chat conversations and streaming follow the server contract', () async {
    final seen = <String, http.Request>{};
    final client = MockClient((request) async {
      seen['${request.method} ${request.url.path}'] = request;
      if (request.url.path == '/api/v1/conversations' &&
          request.method == 'GET') {
        return http.Response(
          jsonEncode({
            'conversations': [
              {
                'id': 'conv-1',
                'title': 'Hello',
                'updated_at': '2026-01-01T10:00:00Z',
                'incognito': false,
              },
            ],
          }),
          200,
        );
      }
      if (request.url.path == '/api/v1/conversations' &&
          request.method == 'POST') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'id': 'conv-2',
            'title': body['title'],
            'incognito': body['incognito'],
          }),
          200,
        );
      }
      if (request.url.path.endsWith('/messages')) {
        return http.Response(
          jsonEncode({
            'messages': [
              {'id': 'm1', 'role': 'user', 'content': 'Hi'},
              {'id': 'm2', 'role': 'assistant', 'content': 'Hello!'},
            ],
          }),
          200,
        );
      }
      if (request.url.path == '/chat/stream') {
        return http.Response(
          [
            '{"type":"status","message":"Thinking"}',
            '{"type":"tool_start","tool":"web_search"}',
            '{"type":"done","response":"Hello!","status":"succeeded"}',
            '',
          ].join('\n'),
          200,
        );
      }
      return http.Response('{}', 404);
    });

    final api = ViraApi('http://localhost:8000', client: client)
      ..sessionId = 'session-123';

    final conversations = await api.conversations();
    expect(conversations.single.id, 'conv-1');
    expect(
      seen['GET /api/v1/conversations']!.headers['Authorization'],
      'Bearer session-123',
    );

    final created = await api.createConversation(title: 'New chat');
    expect(created.id, 'conv-2');

    final messages = await api.conversationMessages('conv-1');
    expect(messages.length, 2);
    expect(messages.last.content, 'Hello!');

    final events = await api
        .streamChat(message: 'Hi', conversationId: 'conv-1')
        .toList();
    expect(events.map((event) => event.type), ['status', 'tool_start', 'done']);
    expect(events.last.response, 'Hello!');
    final request = seen['POST /chat/stream']!;
    expect(request.headers['Idempotency-Key'], isNotEmpty);
    expect(jsonDecode(request.body)['conversation_id'], 'conv-1');
  });

  test(
    'chat stream surfaces server errors and keeps the message code',
    () async {
      final client = MockClient(
        (request) async => http.Response(
          jsonEncode({
            'detail': 'No chat agent is available.',
            'error': {
              'code': 'unavailable',
              'message': 'No chat agent is available.',
            },
          }),
          503,
        ),
      );
      final api = ViraApi('http://localhost:8000', client: client)
        ..sessionId = 'session-123';

      await expectLater(
        api.streamChat(message: 'Hi').toList(),
        throwsA(
          isA<ViraApiException>()
              .having((error) => error.statusCode, 'statusCode', 503)
              .having(
                (error) => error.message,
                'message',
                contains('No chat agent'),
              ),
        ),
      );
    },
  );

  test('stream labels use the server status, tool and check fields', () {
    expect(
      const ChatStreamEvent('status', {'label': 'Thinking'}).label,
      'Thinking',
    );
    expect(
      const ChatStreamEvent('tool_start', {
        'tool': 'database_query.database_query',
      }).label,
      'Using database_query',
    );
    expect(
      const ChatStreamEvent('check', {'text': 'Retrying'}).label,
      'Retrying',
    );
    expect(
      const ChatStreamEvent('thought', {'text': 'reasoning'}).label,
      'Thinking…',
    );
  });
}

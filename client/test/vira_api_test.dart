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

  test('notification stream yields parsed agent notifications', () async {
    final client = MockClient((request) async {
      expect(request.method, 'GET');
      expect(request.url.path, '/api/v1/notifications/stream');
      expect(request.headers['Authorization'], 'Bearer session-123');
      return http.Response(
        '${jsonEncode({'type': 'ready'})}\n'
        '${jsonEncode({
          'type': 'notification',
          'notification': {
            'id': 'n1',
            'title': 'Morning brief',
            'body': 'Today: review the plan.',
            'kind': 'agent_schedule',
            'status': 'delivered',
            'channel': 'inapp',
            'created_at': '2026-11-21T07:30:00+00:00',
            'data': {'schedule_id': 's1'},
          },
        })}\n',
        200,
      );
    });
    final api = ViraApi('http://localhost:8000/', client: client)
      ..sessionId = 'session-123';
    final items = await api.streamNotifications().toList();
    expect(items.single.id, 'n1');
    expect(items.single.title, 'Morning brief');
    expect(items.single.scheduleId, 's1');
  });

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

  test(
    'diagnostic reports use the authenticated diagnostics endpoint',
    () async {
      final client = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/api/v1/diagnostics');
        expect(request.headers['Authorization'], 'Bearer session-123');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['platform'], 'linux');
        expect(body['events'], isEmpty);
        return http.Response(jsonEncode({'status': 'recorded'}), 200);
      });
      final api = ViraApi('http://localhost:8000/', client: client)
        ..sessionId = 'session-123';
      final result = await api.submitDiagnostics({
        'platform': 'linux',
        'app_version': '1.0.0',
        'events': <Map<String, dynamic>>[],
      });
      expect(result['status'], 'recorded');
    },
  );

  test('agent inbox and schedule routes parse the server contract', () async {
    final client = MockClient((request) async {
      switch ('${request.method} ${request.url.path}') {
        case 'GET /api/v1/notifications':
          return http.Response(
            jsonEncode({
              'notifications': [
                {
                  'id': 'n1',
                  'title': 'Morning brief',
                  'body': 'Today: review the plan.',
                  'kind': 'agent_schedule',
                  'status': 'delivered',
                  'channel': 'inapp',
                  'created_at': '2026-11-21T07:30:00+00:00',
                  'data': {
                    'schedule_id': 's1',
                    'run_id': 'run-uuid',
                    'agent_id': 'morning-brief',
                  },
                },
              ],
            }),
            200,
          );
        case 'GET /api/v1/notifications/unread-count':
          return http.Response(jsonEncode({'unread': 1}), 200);
        case 'POST /api/v1/notifications/n1/read':
          return http.Response('{}', 200);
        case 'GET /api/v1/agent-schedules':
          return http.Response(
            jsonEncode({
              'schedules': [
                {
                  'id': 's1',
                  'agent_id': 'morning-brief',
                  'name': 'Morning brief',
                  'message': 'Write my brief.',
                  'schedule_type': 'daily',
                  'time_of_day': '07:30',
                  'timezone': 'Asia/Kolkata',
                  'enabled': true,
                  'channels': ['inapp'],
                  'input': {'mode': 'morning'},
                  'next_run_at': '2026-11-22T02:00:00+00:00',
                },
              ],
            }),
            200,
          );
        case 'POST /api/v1/agent-schedules/s1/run':
          return http.Response(jsonEncode({'status': 'queued'}), 200);
        case 'GET /api/v1/agent-schedules/s1/runs':
          return http.Response(
            jsonEncode({
              'runs': [
                {
                  'id': 'row1',
                  'schedule_id': 's1',
                  'agent_id': 'morning-brief',
                  'run_id': 'run-uuid',
                  'status': 'ok',
                  'result': 'Today: review the plan.',
                  'error': null,
                  'started_at': '2026-11-21T07:30:00+00:00',
                },
              ],
            }),
            200,
          );
        case 'GET /api/v1/agent-schedules/s1/runs/row1':
          return http.Response(
            jsonEncode({
              'run': {
                'id': 'row1',
                'schedule_id': 's1',
                'run_id': 'run-uuid',
                'status': 'ok',
                'result': 'Today: review the plan.',
              },
              'timeline': [
                {
                  'type': 'schedule.started',
                  'data': {'schedule_id': 's1'},
                },
              ],
            }),
            200,
          );
      }
      return http.Response('{}', 404);
    });

    final api = ViraApi('http://localhost:8000/', client: client)
      ..sessionId = 'session-123';
    final notifications = await api.notifications();
    expect(notifications.single.title, 'Morning brief');
    expect(notifications.single.scheduleId, 's1');
    expect(notifications.single.isRead, isFalse);
    expect(await api.unreadNotificationCount(), 1);
    await api.markNotificationRead('n1');

    final schedules = await api.agentSchedules();
    expect(schedules.single.agentId, 'morning-brief');
    expect(schedules.single.cadence, 'Daily 07:30');
    expect(schedules.single.input['mode'], 'morning');
    await api.runAgentSchedule('s1');

    final runs = await api.agentScheduleRuns('s1');
    expect(runs.single.ok, isTrue);
    expect(runs.single.runId, 'run-uuid');
    final detail = await api.agentScheduleRun('s1', 'row1');
    expect(detail.run.result, 'Today: review the plan.');
    expect(detail.timeline.single['type'], 'schedule.started');
  });

  test('agent recipes and schedule mutations follow the contract', () async {
    final client = MockClient((request) async {
      switch ('${request.method} ${request.url.path}') {
        case 'GET /api/v1/agent-recipes':
          return http.Response(
            jsonEncode({
              'agents': [
                {
                  'id': 'focus-coach',
                  'name': 'Focus Coach',
                  'pitch': 'Measured coaching.',
                  'status': 'implemented',
                  'agent_id': 'focus-coach',
                  'daily_trigger': 'evening',
                  'architecture': 'single',
                  'required_tools': ['insights'],
                  'schedule_modes': ['morning', 'evening', 'weekly'],
                  'default_mode': 'evening',
                  'outputs': ['review'],
                  'why_users_return': 'Daily habit.',
                  'default_schedule': {
                    'schedule_type': 'daily',
                    'time_of_day': '18:30',
                    'timezone': 'UTC',
                    'input': {'mode': 'evening'},
                  },
                },
              ],
            }),
            200,
          );
        case 'POST /api/v1/agent-schedules':
          expect(request.headers['Authorization'], 'Bearer session-123');
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['agent_id'], 'focus-coach');
          expect(body['input']['mode'], 'evening');
          return http.Response(
            jsonEncode({
              'id': 's2',
              'agent_id': 'focus-coach',
              'name': 'Evening review',
              'message': 'Review my day',
              'schedule_type': 'daily',
              'time_of_day': '18:30',
              'timezone': 'UTC',
              'enabled': true,
              'channels': ['inapp'],
              'input': {'mode': 'evening'},
            }),
            201,
          );
        case 'PATCH /api/v1/agent-schedules/s2':
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['enabled'], isFalse);
          return http.Response(
            jsonEncode({
              'id': 's2',
              'agent_id': 'focus-coach',
              'name': 'Evening review',
              'message': 'Review my day',
              'schedule_type': 'daily',
              'time_of_day': '18:30',
              'timezone': 'UTC',
              'enabled': false,
              'channels': ['inapp'],
              'input': {'mode': 'evening'},
            }),
            200,
          );
        case 'DELETE /api/v1/agent-schedules/s2':
          return http.Response('{}', 204);
      }
      return http.Response('{}', 404);
    });

    final api = ViraApi('http://localhost:8000/', client: client)
      ..sessionId = 'session-123';
    final recipes = await api.agentRecipes();
    expect(recipes.single.available, isTrue);
    expect(recipes.single.scheduleModes, contains('evening'));
    expect(recipes.single.defaultMode, 'evening');

    final created = await api.createAgentSchedule(
      agentId: 'focus-coach',
      name: 'Evening review',
      message: 'Review my day',
      scheduleType: 'daily',
      timezone: 'UTC',
      timeOfDay: '18:30',
      input: {'mode': 'evening'},
    );
    expect(created.id, 's2');
    expect(created.input['mode'], 'evening');

    final paused = await api.updateAgentSchedule('s2', {'enabled': false});
    expect(paused.enabled, isFalse);
    await api.deleteAgentSchedule('s2');
  });
}

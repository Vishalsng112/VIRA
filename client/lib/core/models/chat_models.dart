/// Conversation and message models exchanged with the VIRA chat API.
class ChatConversation {
  const ChatConversation({
    required this.id,
    required this.title,
    this.updatedAt,
    this.createdAt,
    this.incognito = false,
    this.archived = false,
  });

  final String id;
  final String title;
  final DateTime? updatedAt;
  final DateTime? createdAt;
  final bool incognito;
  final bool archived;

  factory ChatConversation.fromJson(Map<String, dynamic> json) =>
      ChatConversation(
        id: (json['id'] ?? json['conversation_id'] ?? '').toString(),
        title: (json['title'] ?? 'New chat').toString(),
        updatedAt: DateTime.tryParse((json['updated_at'] ?? '').toString()),
        createdAt: DateTime.tryParse((json['created_at'] ?? '').toString()),
        incognito: json['incognito'] == true,
        archived: json['archived'] == true,
      );
}

class ChatMessage {
  const ChatMessage({
    required this.role,
    required this.content,
    this.runId,
    this.createdAt,
    this.trace = const [],
    this.pending = false,
    this.failed = false,
  });

  final String role;
  final String content;
  final String? runId;
  final DateTime? createdAt;
  final List<Map<String, dynamic>> trace;
  final bool pending;
  final bool failed;

  bool get isUser => role == 'user';

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final rawTrace = json['trace'];
    var trace = <Map<String, dynamic>>[];
    if (rawTrace is List) {
      trace = rawTrace.whereType<Map>().map(Map<String, dynamic>.from).toList();
    } else {
      final metadata = json['metadata'];
      if (metadata is Map && metadata['trace'] is List) {
        trace = (metadata['trace'] as List)
            .whereType<Map>()
            .map(Map<String, dynamic>.from)
            .toList();
      }
    }
    return ChatMessage(
      role: (json['role'] ?? 'assistant').toString(),
      content: (json['content'] ?? '').toString(),
      runId: json['run_id']?.toString(),
      createdAt: DateTime.tryParse((json['created_at'] ?? '').toString()),
      trace: trace,
    );
  }

  ChatMessage copyWith({
    String? content,
    bool? pending,
    bool? failed,
    List<Map<String, dynamic>>? trace,
  }) => ChatMessage(
    role: role,
    content: content ?? this.content,
    runId: runId,
    createdAt: createdAt,
    trace: trace ?? this.trace,
    pending: pending ?? this.pending,
    failed: failed ?? this.failed,
  );
}

/// One NDJSON event from `POST /chat/stream`.
class ChatStreamEvent {
  const ChatStreamEvent(this.type, this.data);

  final String type;
  final Map<String, dynamic> data;

  String? get detail => data['detail']?.toString();
  String? get response => data['response']?.toString();
  int? get status => (data['status'] as num?)?.toInt();

  /// A short human label for the live activity line.
  String? get label {
    switch (type) {
      case 'status':
        return data['message']?.toString() ?? data['status']?.toString();
      case 'thought':
        return 'Thinking…';
      case 'tool_start':
        final name = data['tool'] ?? data['name'] ?? 'tool';
        return 'Using $name';
      case 'tool_end':
        final name = data['tool'] ?? data['name'] ?? 'tool';
        return 'Finished $name';
      case 'check':
        return data['message']?.toString();
      default:
        return null;
    }
  }
}

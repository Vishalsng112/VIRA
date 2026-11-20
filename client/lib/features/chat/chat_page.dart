import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/widgets.dart';
import '../../core/models/chat_models.dart';
import '../../data/api/vira_api.dart';

/// Chat with the VIRA server's Chatbot agent, streamed live.
class ChatPage extends StatefulWidget {
  const ChatPage({super.key});

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  late final AppController _controller;
  final _composer = TextEditingController();
  final _composerFocus = FocusNode();
  final _search = TextEditingController();
  final _scroll = ScrollController();

  List<ChatConversation> _conversations = const [];
  List<ChatMessage> _messages = const [];
  ChatConversation? _selected;
  List<String> _activity = const [];
  String? _error;
  String _searchText = '';
  bool _loadingList = true;
  bool _loadingMessages = false;
  bool _sending = false;
  bool _showList = true;
  bool _incognito = false;
  bool _disposed = false;

  static const _suggestions = [
    'Summarise how I used this device today',
    'What can you help me with?',
    'Plan my focus time for tomorrow',
    'Explain my latest VIRA insights',
  ];

  ViraApi? get _api => _controller.api;

  @override
  void initState() {
    super.initState();
    _controller = AppScope.of(context, listen: false);
    _bootstrap();
  }

  @override
  void dispose() {
    _disposed = true;
    _composer.dispose();
    _composerFocus.dispose();
    _search.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    await _loadConversations(selectFirst: true);
  }

  Future<void> _loadConversations({bool selectFirst = false}) async {
    final api = _api;
    if (api == null) {
      _set(() {
        _loadingList = false;
        _error = 'This device is not connected to a VIRA server.';
      });
      return;
    }
    try {
      final items = await api.conversations();
      if (_disposed) return;
      ChatConversation? selected = _selected;
      if (selected != null) {
        final stillThere = items.where((item) => item.id == selected!.id);
        selected = stillThere.isEmpty ? null : stillThere.first;
      }
      if (selected == null && selectFirst && items.isNotEmpty) {
        selected = items.first;
      }
      _set(() {
        _conversations = items;
        _selected = selected;
        _loadingList = false;
        _error = null;
        if (selected != null) _showList = false;
      });
      if (selected != null && (selectFirst || _messages.isEmpty)) {
        await _loadMessages(selected.id);
      }
    } on ViraApiException catch (error) {
      if (_disposed) return;
      _set(() {
        _loadingList = false;
        _error = _friendly(error);
      });
    }
  }

  Future<void> _loadMessages(String id) async {
    final api = _api;
    if (api == null) return;
    _set(() => _loadingMessages = true);
    try {
      final items = await api.conversationMessages(id);
      if (_disposed) return;
      _set(() {
        _messages = items;
        _loadingMessages = false;
        _error = null;
      });
      _scrollToEnd();
    } on ViraApiException catch (error) {
      if (_disposed) return;
      _set(() {
        _loadingMessages = false;
        _error = _friendly(error);
      });
    }
  }

  void _set(VoidCallback fn) {
    if (_disposed || !mounted) return;
    setState(fn);
  }

  String _friendly(ViraApiException error) {
    if (error.isTransport) {
      return 'We cannot reach your VIRA server right now. Check that it is running and try again.';
    }
    if (error.statusCode == 503) {
      return 'The VIRA Chatbot is turned off on the server. Ask an administrator to enable the Chatbot agent, then try again.';
    }
    if (error.isAuthFailure) {
      return 'Your session expired. Sign in again from Settings to keep chatting.';
    }
    if (error.statusCode == 504) {
      return 'VIRA took too long to answer. Your message was saved — try asking again.';
    }
    return error.message;
  }

  Future<void> _select(ChatConversation conversation) async {
    _set(() {
      _selected = conversation;
      _messages = const [];
      _activity = const [];
      _error = null;
      _showList = false;
      _incognito = conversation.incognito;
    });
    await _loadMessages(conversation.id);
  }

  Future<void> _newChat({bool incognito = false}) async {
    _set(() {
      _selected = null;
      _messages = const [];
      _activity = const [];
      _error = null;
      _incognito = incognito;
      _showList = false;
    });
    await Future<void>.delayed(const Duration(milliseconds: 50));
    _composerFocus.requestFocus();
  }

  Future<void> _deleteConversation(ChatConversation conversation) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Delete this chat?'),
        content: Text(
          '"${conversation.title}" and its messages will be removed from your VIRA server.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(dialogContext).colorScheme.error,
            ),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || _api == null) return;
    try {
      await _api!.deleteConversation(conversation.id);
      if (_selected?.id == conversation.id) {
        _set(() {
          _selected = null;
          _messages = const [];
        });
      }
      await _loadConversations();
    } on ViraApiException catch (error) {
      _snack(_friendly(error));
    }
  }

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _composer.text).trim();
    if (text.isEmpty || _sending) return;
    final api = _api;
    if (api == null) {
      _snack('This device is not connected to a VIRA server.');
      return;
    }
    _composer.clear();
    _set(() {
      _sending = true;
      _error = null;
      _activity = const [];
      _messages = [
        ..._messages,
        ChatMessage(role: 'user', content: text, createdAt: DateTime.now()),
        ChatMessage(
          role: 'assistant',
          content: '',
          createdAt: DateTime.now(),
          pending: true,
        ),
      ];
    });
    _scrollToEnd();

    try {
      var conversation = _selected;
      if (conversation == null) {
        conversation = await api.createConversation(
          title: text.length > 48 ? text.substring(0, 48) : text,
          incognito: _incognito,
        );
        _set(() => _selected = conversation);
      }

      String? answer;
      final activity = <String>[];
      await for (final event in api.streamChat(
        message: text,
        conversationId: conversation.id,
      )) {
        if (event.type == 'done') {
          answer = event.response ?? '';
          continue;
        }
        if (event.type == 'error') {
          throw ViraApiException(
            event.status ?? 500,
            'chat_failed',
            event.detail ?? 'VIRA could not answer that message.',
          );
        }
        final label = event.label;
        if (label != null && label.trim().isNotEmpty) {
          activity.add(label);
          if (activity.length > 4) activity.removeAt(0);
          _set(() {
            _activity = List<String>.from(activity);
          });
        }
        _scrollToEnd();
      }

      if (answer == null || answer.trim().isEmpty) {
        throw ViraApiException(
          0,
          'empty_answer',
          'VIRA finished without an answer. Please try asking again.',
        );
      }
      _set(() {
        _messages = [
          for (final message in _messages)
            if (message.pending)
              message.copyWith(content: answer, pending: false)
            else
              message,
        ];
        _sending = false;
        _activity = const [];
      });
      _scrollToEnd();
      await _loadConversations();
      if (_selected != null) {
        await _loadMessages(_selected!.id);
      }
    } on ViraApiException catch (error) {
      _failPending(_friendly(error));
    } on Object catch (error) {
      _failPending(error.toString());
    }
  }

  void _failPending(String reason) {
    _set(() {
      _sending = false;
      _activity = const [];
      _error = reason;
      _messages = [
        for (final message in _messages)
          if (message.pending)
            message.copyWith(
              content: message.content.isEmpty ? reason : message.content,
              pending: false,
              failed: true,
            )
          else
            message,
      ];
    });
    _scrollToEnd();
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 260),
        curve: Curves.easeOutCubic,
      );
    });
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  List<ChatConversation> get _filtered {
    final query = _searchText.trim().toLowerCase();
    if (query.isEmpty) return _conversations;
    return _conversations
        .where((item) => item.title.toLowerCase().contains(query))
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final wide = width >= 1000;
    if (wide) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(4, 4, 4, 4),
        child: Row(
          children: [
            SizedBox(width: 300, child: _conversationPanel()),
            const SizedBox(width: 14),
            Expanded(child: _chatSurface()),
          ],
        ),
      );
    }
    if (_showList) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(4, 4, 4, 4),
        child: _conversationPanel(fullScreen: true),
      );
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 4, 4, 4),
      child: _chatSurface(compact: true),
    );
  }

  Widget _conversationPanel({bool fullScreen = false}) {
    final theme = Theme.of(context);
    return GlassCard(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'Conversations',
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.3,
                  ),
                ),
              ),
              IconButton(
                tooltip: 'New chat',
                onPressed: () => _newChat(),
                icon: const Icon(Icons.add_comment_outlined),
              ),
            ],
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _search,
            onChanged: (value) => _set(() => _searchText = value),
            decoration: const InputDecoration(
              hintText: 'Search chats',
              prefixIcon: Icon(Icons.search_rounded, size: 20),
              isDense: true,
            ),
          ),
          const SizedBox(height: 10),
          Expanded(
            child: _loadingList
                ? const Center(child: CircularProgressIndicator())
                : _filtered.isEmpty
                ? EmptyState(
                    icon: Icons.forum_outlined,
                    title: _conversations.isEmpty
                        ? 'No conversations yet'
                        : 'No matches',
                    message: _conversations.isEmpty
                        ? 'Start a chat and your conversation history will appear here.'
                        : 'Try a different search.',
                    action: _conversations.isEmpty
                        ? FilledButton.tonalIcon(
                            onPressed: () => _newChat(),
                            icon: const Icon(Icons.auto_awesome),
                            label: const Text('Start chatting'),
                          )
                        : null,
                  )
                : ListView.separated(
                    itemCount: _filtered.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 4),
                    itemBuilder: (context, index) {
                      final conversation = _filtered[index];
                      final active = conversation.id == _selected?.id;
                      return Material(
                        color: active
                            ? theme.colorScheme.primary.withValues(alpha: 0.12)
                            : Colors.transparent,
                        borderRadius: BorderRadius.circular(16),
                        child: InkWell(
                          borderRadius: BorderRadius.circular(16),
                          onTap: () => _select(conversation),
                          child: Padding(
                            padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
                            child: Row(
                              children: [
                                Icon(
                                  conversation.incognito
                                      ? Icons.visibility_off_outlined
                                      : Icons.chat_bubble_outline,
                                  size: 18,
                                  color: active
                                      ? theme.colorScheme.primary
                                      : theme.colorScheme.onSurfaceVariant,
                                ),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        conversation.title,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: theme.textTheme.bodyMedium
                                            ?.copyWith(
                                              fontWeight: active
                                                  ? FontWeight.w700
                                                  : FontWeight.w500,
                                            ),
                                      ),
                                      Text(
                                        _relative(conversation.updatedAt),
                                        style: theme.textTheme.labelSmall
                                            ?.copyWith(
                                              color: theme
                                                  .colorScheme
                                                  .onSurfaceVariant,
                                            ),
                                      ),
                                    ],
                                  ),
                                ),
                                PopupMenuButton<String>(
                                  tooltip: 'Chat options',
                                  onSelected: (value) {
                                    if (value == 'delete') {
                                      _deleteConversation(conversation);
                                    }
                                  },
                                  itemBuilder: (context) => const [
                                    PopupMenuItem(
                                      value: 'delete',
                                      child: Text('Delete chat'),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        ),
                      );
                    },
                  ),
          ),
          if (fullScreen) ...[
            const SizedBox(height: 6),
            Text(
              'Chats stay on your own VIRA server.',
              textAlign: TextAlign.center,
              style: theme.textTheme.labelSmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _chatSurface({bool compact = false}) {
    final theme = Theme.of(context);
    final conversation = _selected;
    return GlassCard(
      padding: EdgeInsets.zero,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 10, 10),
            child: Row(
              children: [
                if (compact)
                  IconButton(
                    tooltip: 'All chats',
                    onPressed: () => _set(() => _showList = true),
                    icon: const Icon(Icons.menu_rounded),
                  ),
                Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(
                      colors: [Color(0xFF5B6CFF), Color(0xFF9B6BFF)],
                    ),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(
                    Icons.auto_awesome,
                    size: 19,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(width: 11),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        conversation?.title ?? 'New chat',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      Text(
                        _sending
                            ? (_activity.isEmpty
                                  ? 'VIRA is working…'
                                  : _activity.last)
                            : 'Private assistant on your VIRA server',
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: 'New chat',
                  onPressed: () => _newChat(),
                  icon: const Icon(Icons.edit_square),
                ),
                if (!compact)
                  IconButton(
                    tooltip: 'All chats',
                    onPressed: () => _set(() => _showList = true),
                    icon: const Icon(Icons.history_rounded),
                  ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: _loadingMessages
                ? const Center(child: CircularProgressIndicator())
                : _messages.isEmpty
                ? _welcome()
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(16, 18, 16, 12),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      return _MessageBubble(message: _messages[index]);
                    },
                  ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 4, 14, 4),
              child: Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: theme.colorScheme.error.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: theme.colorScheme.error.withValues(alpha: 0.22),
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      Icons.error_outline,
                      size: 18,
                      color: theme.colorScheme.error,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _error!,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.error,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: 'Dismiss',
                      onPressed: () => _set(() => _error = null),
                      icon: const Icon(Icons.close, size: 18),
                    ),
                  ],
                ),
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 12),
            child: _composerBar(theme),
          ),
        ],
      ),
    );
  }

  Widget _welcome() {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 30, 24, 20),
      child: Column(
        children: [
          Container(
            width: 72,
            height: 72,
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [
                  Color(0xFF5B6CFF),
                  Color(0xFF9B6BFF),
                  Color(0xFFFF7AB6),
                ],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(24),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFF9B6BFF).withValues(alpha: 0.32),
                  blurRadius: 28,
                  offset: const Offset(0, 14),
                ),
              ],
            ),
            child: const Icon(
              Icons.auto_awesome,
              color: Colors.white,
              size: 34,
            ),
          ),
          const SizedBox(height: 20),
          Text(
            'How can I help?',
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w800,
              letterSpacing: -0.6,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Ask about your day, your device, or anything else. '
            'The conversation never leaves your VIRA server.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
              height: 1.5,
            ),
          ),
          const SizedBox(height: 22),
          Wrap(
            alignment: WrapAlignment.center,
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final suggestion in _suggestions)
                ActionChip(
                  label: Text(suggestion),
                  onPressed: _sending ? null : () => _send(suggestion),
                ),
            ],
          ),
          if (_incognito) ...[
            const SizedBox(height: 16),
            const StatusPill(
              label: 'Private chat · not saved after closing',
              tone: StatusTone.info,
              icon: Icons.visibility_off_outlined,
            ),
          ],
        ],
      ),
    );
  }

  Widget _composerBar(ThemeData theme) {
    return GlassBar(
      radius: 22,
      padding: const EdgeInsets.fromLTRB(10, 6, 6, 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: TextField(
              controller: _composer,
              focusNode: _composerFocus,
              minLines: 1,
              maxLines: 6,
              textInputAction: TextInputAction.newline,
              onChanged: (_) => _set(() {}),
              decoration: const InputDecoration(
                hintText: 'Message VIRA…',
                filled: false,
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                contentPadding: EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 12,
                ),
              ),
            ),
          ),
          const SizedBox(width: 4),
          IconButton.filled(
            tooltip: 'Send',
            onPressed: _sending || _composer.text.trim().isEmpty
                ? null
                : () => _send(),
            icon: _sending
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Icon(Icons.arrow_upward_rounded),
            style: IconButton.styleFrom(
              backgroundColor: theme.colorScheme.primary,
              foregroundColor: Colors.white,
              disabledBackgroundColor:
                  theme.colorScheme.surfaceContainerHighest,
              minimumSize: const Size(46, 46),
            ),
          ),
        ],
      ),
    );
  }

  String _relative(DateTime? time) {
    if (time == null) return '';
    final local = time.toLocal();
    final diff = DateTime.now().difference(local);
    if (diff.inMinutes < 1) return 'Just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes} min ago';
    if (diff.inHours < 24) return '${diff.inHours} h ago';
    if (diff.inDays < 7) return '${diff.inDays} d ago';
    return '${local.day}/${local.month}/${local.year}';
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (message.isUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.only(bottom: 12, left: 48),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            gradient: const LinearGradient(
              colors: [Color(0xFF5B6CFF), Color(0xFF7C6BFF)],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(22),
              topRight: Radius.circular(22),
              bottomLeft: Radius.circular(22),
              bottomRight: Radius.circular(6),
            ),
            boxShadow: [
              BoxShadow(
                color: const Color(0xFF5B6CFF).withValues(alpha: 0.26),
                blurRadius: 18,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: SelectableText(
            message.content,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 15,
              height: 1.45,
            ),
          ),
        ),
      );
    }
    final failed = message.failed;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14, right: 24),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 30,
            height: 30,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: failed
                    ? [theme.colorScheme.error, theme.colorScheme.error]
                    : const [Color(0xFF5B6CFF), Color(0xFF9B6BFF)],
              ),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(
              failed ? Icons.error_outline : Icons.auto_awesome,
              color: Colors.white,
              size: 16,
            ),
          ),
          const SizedBox(width: 10),
          Flexible(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerLow.withValues(
                  alpha: 0.82,
                ),
                borderRadius: const BorderRadius.only(
                  topLeft: Radius.circular(6),
                  topRight: Radius.circular(22),
                  bottomLeft: Radius.circular(22),
                  bottomRight: Radius.circular(22),
                ),
                border: Border.all(
                  color: theme.colorScheme.outlineVariant.withValues(
                    alpha: 0.6,
                  ),
                ),
              ),
              child: message.content.isEmpty && !failed
                  ? const _TypingDots()
                  : SelectableText(
                      message.content,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        height: 1.55,
                        color: failed ? theme.colorScheme.error : null,
                      ),
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TypingDots extends StatelessWidget {
  const _TypingDots();

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.onSurfaceVariant;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var index = 0; index < 3; index++)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 2),
            child: Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.5 + index * 0.2),
                shape: BoxShape.circle,
              ),
            ),
          ),
      ],
    );
  }
}

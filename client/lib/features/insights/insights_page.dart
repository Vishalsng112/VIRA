import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/widgets.dart';
import '../../core/catalog/app_catalog.dart';
import '../../core/config/app_config.dart';
import '../../core/models/app_usage.dart';
import '../../core/models/device_signals.dart';
import '../../core/models/focus_session.dart';
import '../../core/utils/duration_format.dart';
import '../../data/storage/outbox_store.dart';
import '../../services/insights/insight_engine.dart';

enum _Range { today, week }

class InsightsPage extends StatefulWidget {
  const InsightsPage({super.key});

  @override
  State<InsightsPage> createState() => _InsightsPageState();
}

class _InsightsPageState extends State<InsightsPage> {
  _Range _range = _Range.today;
  UsageDay _today = const UsageDay(date: '', apps: {});
  List<UsageDay> _recent = const [];
  SessionDay _sessionToday = const SessionDay(date: '');
  List<SessionDay> _recentSessions = const [];
  FocusSession? _activeFocus;
  List<FocusSession> _recentFocus = const [];
  bool _loading = true;
  late final AppController _controller;
  Timer? _focusTimer;

  @override
  void initState() {
    super.initState();
    _controller = AppScope.of(context, listen: false);
    _controller.addListener(_reload);
    _focusTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _activeFocus != null) setState(() {});
    });
    _load();
  }

  @override
  void dispose() {
    _focusTimer?.cancel();
    _controller.removeListener(_reload);
    super.dispose();
  }

  void _reload() {
    if (mounted) _load();
  }

  Future<void> _load() async {
    final today = await _controller.usageToday();
    final recent = await _controller.usageRecent(days: 7);
    final sessionToday = await _controller.sessionToday();
    final recentSessions = await _controller.sessionRecent(days: 7);
    final activeFocus = await _controller.activeFocus();
    final recentFocus = await _controller.recentFocus(days: 7);
    if (!mounted) return;
    setState(() {
      _today = today;
      _recent = recent;
      _sessionToday = sessionToday;
      _recentSessions = recentSessions;
      _activeFocus = activeFocus;
      _recentFocus = recentFocus;
      _loading = false;
    });
  }

  Map<String, AppUsageSample> get _selectedApps {
    final days = _range == _Range.today ? [_today] : _recent;
    final merged = <String, AppUsageSample>{};
    for (final day in days) {
      for (final entry in day.apps.entries) {
        final existing = merged[entry.key];
        merged[entry.key] = existing == null
            ? entry.value
            : existing.merge(entry.value);
      }
    }
    return merged;
  }

  int get _totalMs =>
      _selectedApps.values.fold(0, (total, app) => total + app.foregroundMs);

  List<SessionDay> get _selectedSessions =>
      _range == _Range.today ? [_sessionToday] : _recentSessions;

  int get _interactiveMs =>
      _selectedSessions.fold(0, (total, day) => total + day.interactiveMs);

  int get _unlocks =>
      _selectedSessions.fold(0, (total, day) => total + day.unlocks);

  int get _longestSessionMs => _selectedSessions.fold(
    0,
    (longest, day) => day.longestSessionMs > longest
        ? day.longestSessionMs
        : longest,
  );

  int get _currentSessionMs => _sessionToday.currentSessionMs;

  List<FocusSession> get _selectedFocus {
    if (_range == _Range.week) return _recentFocus;
    final now = DateTime.now();
    return _recentFocus.where((session) {
      final local = session.startedAt.toLocal();
      return local.year == now.year &&
          local.month == now.month &&
          local.day == now.day;
    }).toList();
  }

  Map<String, int> get _categoryTotals {
    final totals = <String, int>{};
    for (final app in _selectedApps.values) {
      totals[app.category] = (totals[app.category] ?? 0) + app.foregroundMs;
    }
    return totals;
  }

  Future<void> _clearHistory() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear local usage history?'),
        content: const Text(
          'This removes the on-device app-usage and screen-session ledgers. Events already sent to the VIRA server are not affected.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
            ),
            child: const Text('Clear'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await _controller.clearLocalHistory();
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final theme = Theme.of(context);
    final apps = _selectedApps.values.toList()
      ..sort((a, b) => b.foregroundMs.compareTo(a.foregroundMs));
    final android = controller.profile?.platform == 'android';
    final hasAny = apps.isNotEmpty || _interactiveMs > 0;
    final report = InsightEngine.build(
      usage: _range == _Range.today ? [_today] : _recent,
      sessions: _selectedSessions,
      focus: _selectedFocus,
      health: controller.health,
    );
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 980),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Insights',
                              style: theme.textTheme.headlineSmall?.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'On-device summary of your app usage.',
                              style: theme.textTheme.bodyMedium?.copyWith(
                                color: theme.colorScheme.onSurfaceVariant,
                              ),
                            ),
                          ],
                        ),
                      ),
                      if (apps.isNotEmpty)
                        TextButton.icon(
                          onPressed: _clearHistory,
                          icon: const Icon(Icons.delete_sweep_outlined),
                          label: const Text('Clear'),
                        ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  SegmentedButton<_Range>(
                    segments: const [
                      ButtonSegment(
                        value: _Range.today,
                        icon: Icon(Icons.today_outlined),
                        label: Text('Today'),
                      ),
                      ButtonSegment(
                        value: _Range.week,
                        icon: Icon(Icons.date_range_outlined),
                        label: Text('7 days'),
                      ),
                    ],
                    selected: {_range},
                    onSelectionChanged: (value) =>
                        setState(() => _range = value.first),
                  ),
                  const SizedBox(height: 16),
                  _FocusCard(
                    active: _activeFocus,
                    recent: _recentFocus,
                    onStart: (minutes) async {
                      await _controller.startFocus(minutes: minutes);
                      await _load();
                    },
                    onStop: () async {
                      await _controller.stopFocus();
                      await _load();
                    },
                  ),
                  const SizedBox(height: 16),
                  if (!_loading) _SmartInsights(report: report),
                  const SizedBox(height: 16),
                  if (_loading)
                    const Padding(
                      padding: EdgeInsets.all(48),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else if (!hasAny)
                    EmptyState(
                      icon: Icons.insights_outlined,
                      title: 'No app usage captured yet',
                      message: android
                          ? 'Enable App usage on the Overview page, then grant Usage Access to VIRA Link in Android settings.'
                          : 'App usage is currently captured on Android. Desktop active-window capture is on the roadmap.',
                      action: android
                          ? FilledButton.icon(
                              onPressed: () => _controller.requestCollectorAccess(
                                collectorAppUsage,
                              ),
                              icon: const Icon(Icons.lock_open_outlined),
                              label: const Text('Open Usage Access settings'),
                            )
                          : null,
                    )
                  else ...[
                    _Summary(
                      screenMs: _interactiveMs > 0 ? _interactiveMs : _totalMs,
                      unlocks: _unlocks,
                      topApp: apps.isEmpty ? null : apps.first,
                      topCategory: apps.isEmpty ? null : _topCategory,
                    ),
                    if (_currentSessionMs >= 45 * 60 * 1000 ||
                        _interactiveMs >= 2 * 60 * 60 * 1000) ...[
                      const SizedBox(height: 16),
                      _BreakCard(
                        currentSessionMs: _currentSessionMs,
                        todayMs: _sessionToday.interactiveMs,
                      ),
                    ],
                    const SizedBox(height: 16),
                    if (apps.isNotEmpty)
                      SectionCard(
                      title: 'Top apps',
                      subtitle: _range == _Range.today
                          ? 'Foreground time today'
                          : 'Foreground time over the last 7 days',
                      child: Column(
                        children: [
                          for (final app in apps.take(10))
                            _AppRow(app: app, maxMs: apps.first.foregroundMs),
                        ],
                      ),
                    ),
                    if (apps.isNotEmpty) ...[
                    const SizedBox(height: 16),
                    SectionCard(
                      title: 'Categories',
                      subtitle: 'How your time is distributed.',
                      child: _CategoryBreakdown(
                        totals: _categoryTotals,
                        totalMs: _totalMs,
                      ),
                    ),
                    ],
                    const SizedBox(height: 16),
                    if (_interactiveMs > 0) ...[
                      SectionCard(
                        title: 'Screen & sessions',
                        subtitle: 'Screen time and rest signals for this range.',
                        child: Column(
                          children: [
                            InfoRow(
                              label: 'Screen time',
                              value: formatDurationMs(_interactiveMs),
                              icon: Icons.phone_android,
                            ),
                            InfoRow(
                              label: 'Unlocks',
                              value: '$_unlocks',
                              icon: Icons.lock_open_outlined,
                            ),
                            InfoRow(
                              label: 'Longest session',
                              value: formatDurationMs(_longestSessionMs),
                              icon: Icons.timelapse,
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(
                              Icons.psychology_outlined,
                              color: theme.colorScheme.primary,
                            ),
                            const SizedBox(width: 14),
                            Expanded(
                              child: Text(
                                'This ledger is local and compact. Later, VIRA agents can use it to answer '
                                'questions such as “how much time did I spend on social apps this week?” '
                                'or to suggest a study/focus plan. Raw app-usage events are also queued '
                                'to the server when sync is enabled.',
                                style: theme.textTheme.bodyMedium?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                  height: 1.5,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  String get _topCategory {
    final totals = _categoryTotals;
    if (totals.isEmpty) return AppCategory.other;
    return (totals.entries.toList()
          ..sort((a, b) => b.value.compareTo(a.value)))
        .first
        .key;
  }
}

class _SmartInsights extends StatelessWidget {
  const _SmartInsights({required this.report});

  final InsightReport report;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SectionCard(
      title: 'Smart insights',
      subtitle: 'Local, rule-based summaries. No data leaves the device for this step.',
      child: Column(
        children: [
          for (final finding in report.findings)
            Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    _icon(finding.tone),
                    color: _color(finding.tone, theme),
                    size: 22,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          finding.title,
                          style: theme.textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          finding.body,
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                            height: 1.4,
                          ),
                        ),
                        if (finding.recommendation != null) ...[
                          const SizedBox(height: 4),
                          Text(
                            finding.recommendation!,
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.primary,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  IconData _icon(InsightTone tone) => switch (tone) {
    InsightTone.success => Icons.check_circle_outline,
    InsightTone.warning => Icons.warning_amber_outlined,
    InsightTone.info => Icons.lightbulb_outline,
    InsightTone.neutral => Icons.hourglass_empty,
  };

  Color _color(InsightTone tone, ThemeData theme) => switch (tone) {
    InsightTone.success => const Color(0xFF137333),
    InsightTone.warning => const Color(0xFFB06000),
    InsightTone.info => theme.colorScheme.primary,
    InsightTone.neutral => theme.colorScheme.onSurfaceVariant,
  };
}

class _FocusCard extends StatelessWidget {
  const _FocusCard({
    required this.active,
    required this.recent,
    required this.onStart,
    required this.onStop,
  });

  final FocusSession? active;
  final List<FocusSession> recent;
  final Future<void> Function(int minutes) onStart;
  final Future<void> Function() onStop;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final now = DateTime.now();
    final today = recent.where((session) {
      final local = session.startedAt.toLocal();
      return local.year == now.year &&
          local.month == now.month &&
          local.day == now.day;
    });
    final completedMs = today.fold(
      0,
      (total, session) => total + session.durationMs,
    );
    final activeMs = active?.durationMs ?? 0;
    final progress = active == null || active!.plannedMs <= 0
        ? 0.0
        : (activeMs / active!.plannedMs).clamp(0.0, 1.0);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(
                    color: theme.colorScheme.primaryContainer,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(
                    Icons.center_focus_strong,
                    color: theme.colorScheme.onPrimaryContainer,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        active == null ? 'Focus session' : active!.label,
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      Text(
                        active == null
                            ? 'Work in a deliberate block. Study, code or write without switching apps.'
                            : '${formatDurationMs(activeMs)} of ${active!.plannedMinutes}m · started ${OutboxStore.prettyClock(active!.startedAt)}',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
                if (active == null)
                  Text(
                    '${formatDurationMs(completedMs + activeMs)} today',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
              ],
            ),
            if (active != null) ...[
              const SizedBox(height: 14),
              ClipRRect(
                borderRadius: BorderRadius.circular(99),
                child: LinearProgressIndicator(
                  value: progress,
                  minHeight: 8,
                  backgroundColor: theme.colorScheme.surfaceContainerHighest,
                ),
              ),
              const SizedBox(height: 14),
              Align(
                alignment: Alignment.centerRight,
                child: FilledButton.icon(
                  onPressed: () => onStop(),
                  icon: const Icon(Icons.stop_circle_outlined),
                  label: const Text('End session'),
                ),
              ),
            ] else ...[
              const SizedBox(height: 16),
              Wrap(
                spacing: 10,
                runSpacing: 8,
                children: [
                  FilledButton.tonalIcon(
                    onPressed: () => onStart(25),
                    icon: const Icon(Icons.play_arrow),
                    label: const Text('Start 25 min'),
                  ),
                  OutlinedButton.icon(
                    onPressed: () => onStart(50),
                    icon: const Icon(Icons.timelapse),
                    label: const Text('Start 50 min'),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Summary extends StatelessWidget {
  const _Summary({
    required this.screenMs,
    required this.unlocks,
    required this.topApp,
    required this.topCategory,
  });

  final int screenMs;
  final int unlocks;
  final AppUsageSample? topApp;
  final String? topCategory;

  @override
  Widget build(BuildContext context) {
    final cards = [
      StatCard(
        icon: Icons.timer_outlined,
        label: 'Screen time',
        value: formatDurationMs(screenMs),
        caption: 'Captured interactive time',
      ),
      StatCard(
        icon: Icons.lock_open_outlined,
        label: 'Unlocks',
        value: '$unlocks',
        caption: 'Screen unlocks in range',
      ),
      StatCard(
        icon: Icons.apps,
        label: 'Most used',
        value: topApp?.label ?? 'No app data',
        caption: topApp == null ? 'Grant Usage Access' : formatDurationMs(topApp!.foregroundMs),
      ),
      StatCard(
        icon: Icons.category_outlined,
        label: 'Top category',
        value: topCategory == null ? '—' : categoryLabel(topCategory!),
        caption: 'Largest share of app time',
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        const spacing = 12.0;
        final columns = constraints.maxWidth >= 860
            ? 4
            : constraints.maxWidth >= 360
            ? 2
            : 1;
        final width =
            (constraints.maxWidth - spacing * (columns - 1)) / columns;
        return Wrap(
          spacing: spacing,
          runSpacing: spacing,
          children: [
            for (final card in cards) SizedBox(width: width, child: card),
          ],
        );
      },
    );
  }
}

class _BreakCard extends StatelessWidget {
  const _BreakCard({required this.currentSessionMs, required this.todayMs});

  final int currentSessionMs;
  final int todayMs;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final longSession = currentSessionMs >= 45 * 60 * 1000;
    return Card(
      color: theme.colorScheme.secondaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              Icons.self_improvement,
              color: theme.colorScheme.onSecondaryContainer,
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    longSession ? 'Time for a short break' : 'Long screen day',
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      color: theme.colorScheme.onSecondaryContainer,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    longSession
                        ? 'This screen session is ${formatDurationMs(currentSessionMs)} long. Look away, stretch, or take a 5-minute break.'
                        : 'You have had ${formatDurationMs(todayMs)} of screen time today. A short walk or a glass of water can help.',
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: theme.colorScheme.onSecondaryContainer,
                      height: 1.4,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AppRow extends StatelessWidget {
  const _AppRow({required this.app, required this.maxMs});

  final AppUsageSample app;
  final int maxMs;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final share = maxMs <= 0 ? 0.0 : app.foregroundMs / maxMs;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(11),
            ),
            child: Icon(
              _categoryIcon(app.category),
              size: 19,
              color: theme.colorScheme.primary,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        app.label,
                        style: theme.textTheme.bodyLarge?.copyWith(
                          fontWeight: FontWeight.w500,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Text(
                      formatDurationMs(app.foregroundMs),
                      style: theme.textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 3),
                Row(
                  children: [
                    Expanded(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(99),
                        child: LinearProgressIndicator(
                          value: share.clamp(0, 1),
                          minHeight: 5,
                          backgroundColor:
                              theme.colorScheme.surfaceContainerHighest,
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Text(
                      categoryLabel(app.category),
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  IconData _categoryIcon(String category) => switch (category) {
    AppCategory.social => Icons.people_outline,
    AppCategory.communication => Icons.chat_bubble_outline,
    AppCategory.productivity => Icons.work_outline,
    AppCategory.education => Icons.school_outlined,
    AppCategory.entertainment => Icons.movie_outlined,
    AppCategory.games => Icons.sports_esports_outlined,
    AppCategory.shopping => Icons.shopping_bag_outlined,
    AppCategory.finance => Icons.account_balance_wallet_outlined,
    AppCategory.health => Icons.favorite_border,
    AppCategory.travel => Icons.map_outlined,
    AppCategory.system => Icons.settings_outlined,
    _ => Icons.apps,
  };
}

class _CategoryBreakdown extends StatelessWidget {
  const _CategoryBreakdown({required this.totals, required this.totalMs});

  final Map<String, int> totals;
  final int totalMs;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final entries = totals.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    if (entries.isEmpty) return const Text('No category data yet.');
    return Column(
      children: [
        for (final entry in entries)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Row(
              children: [
                SizedBox(
                  width: 110,
                  child: Text(
                    categoryLabel(entry.key),
                    style: theme.textTheme.bodyMedium,
                  ),
                ),
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(99),
                    child: LinearProgressIndicator(
                      value: totalMs <= 0 ? 0 : entry.value / totalMs,
                      minHeight: 8,
                      backgroundColor: theme.colorScheme.surfaceContainerHighest,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                SizedBox(
                  width: 58,
                  child: Text(
                    formatDurationMs(entry.value),
                    textAlign: TextAlign.right,
                    style: theme.textTheme.bodySmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

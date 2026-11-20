/// Small, local app catalogue. It gives the first useful category without
/// waiting for the server; server-side models can refine it later.
class AppCategory {
  static const social = 'social';
  static const communication = 'communication';
  static const productivity = 'productivity';
  static const education = 'education';
  static const entertainment = 'entertainment';
  static const browsing = 'browsing';
  static const games = 'games';
  static const shopping = 'shopping';
  static const finance = 'finance';
  static const health = 'health';
  static const travel = 'travel';
  static const system = 'system';
  static const other = 'other';

  static const labels = <String, String>{
    social: 'Social',
    communication: 'Communication',
    productivity: 'Productivity',
    education: 'Education',
    entertainment: 'Entertainment',
    browsing: 'Browsing',
    games: 'Games',
    shopping: 'Shopping',
    finance: 'Finance',
    health: 'Health',
    travel: 'Travel',
    system: 'System',
    other: 'Other',
  };
}

const _rules = <String, List<String>>{
  AppCategory.system: [
    'launcher',
    'systemui',
    'settings',
    'com.android.systemui',
    'com.android.settings',
    'com.android.permissioncontroller',
    'com.google.android.permissioncontroller',
    'com.google.android.packageinstaller',
    'com.google.android.apps.nexuslauncher',
  ],
  AppCategory.communication: [
    'whatsapp',
    'telegram',
    'signal',
    'messenger',
    'discord',
    'slack',
    'teams',
    'zoom',
    'gmail',
    'outlook',
    'mail',
    'phone',
    'dialer',
    'messages',
  ],
  AppCategory.education: [
    'classroom',
    'coursera',
    'udemy',
    'khan',
    'duolingo',
    'edx',
    'brilliant',
    'quizlet',
    'byju',
    'unacademy',
  ],
  AppCategory.productivity: [
    'notion',
    'todoist',
    'ticktick',
    'calendar',
    'docs',
    'sheets',
    'slides',
    'drive',
    'keep',
    'obsidian',
    'evernote',
    'github',
    'gitlab',
    'vscode',
    'code',
    'figma',
    'trello',
    'asana',
    'clickup',
  ],
  AppCategory.games: [
    'game',
    'pubg',
    'clash',
    'candy',
    'roblox',
    'minecraft',
    'fortnite',
    'freefire',
    'amongus',
  ],
  AppCategory.social: [
    'instagram',
    'facebook',
    'twitter',
    ' x.com',
    'snapchat',
    'reddit',
    'linkedin',
    'threads',
    'pinterest',
    'tiktok',
    'tumblr',
  ],
  AppCategory.browsing: [
    'chrome',
    'firefox',
    'edge',
    'brave',
    'safari',
    'browser',
  ],
  AppCategory.entertainment: [
    'youtube',
    'netflix',
    'spotify',
    'prime video',
    'hotstar',
    'twitch',
    'hulu',
    'disney',
    'soundcloud',
    'music',
    'podcast',
  ],
  AppCategory.shopping: [
    'amazon',
    'flipkart',
    'ebay',
    'etsy',
    'myntra',
    'ajio',
    'aliexpress',
  ],
  AppCategory.finance: [
    'bank',
    'paypal',
    'wallet',
    'phonepe',
    'gpay',
    'google pay',
    'paytm',
    'upi',
    'zerodha',
    'groww',
    'binance',
  ],
  AppCategory.health: [
    'fitbit',
    'strava',
    'myfitnesspal',
    'health',
    'meditation',
    'calm',
    'headspace',
    'workout',
    'fitness',
  ],
  AppCategory.travel: [
    'uber',
    'lyft',
    'ola',
    'airbnb',
    'booking',
    'maps',
    'flight',
    'railway',
  ],
};

String categoryForApp(String packageName, String label) {
  final haystack = ' ${packageName.toLowerCase()} ${label.toLowerCase()} ';
  for (final entry in _rules.entries) {
    for (final keyword in entry.value) {
      if (haystack.contains(keyword)) return entry.key;
    }
  }
  return AppCategory.other;
}

String categoryLabel(String category) => AppCategory.labels[category] ?? 'Other';

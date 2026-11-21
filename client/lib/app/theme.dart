import 'package:material_ui/material_ui.dart';

/// VIRA Link design tokens.
///
/// The interface uses an iOS-inspired "liquid glass" language: soft aurora
/// gradients, translucent frosted panels, generous radii and pill controls.
/// Keep colours and measures here so every page feels like one product.
abstract final class ViraPalette {
  static const indigo = Color(0xFF5B6CFF);
  static const violet = Color(0xFF9B6BFF);
  static const pink = Color(0xFFFF7AB6);
  static const cyan = Color(0xFF52D6E8);
  static const mint = Color(0xFF4ADE9B);
  static const amber = Color(0xFFFFB55C);

  static const lightGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFFF7F8FF), Color(0xFFEEF1FF), Color(0xFFFFF3FA)],
  );

  static const darkGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF070A16), Color(0xFF0C1024), Color(0xFF14102C)],
  );

  /// Frosted panel fill.
  static Color glassFill(Brightness brightness) => brightness == Brightness.dark
      ? Colors.white.withValues(alpha: 0.07)
      : Colors.white.withValues(alpha: 0.62);

  /// Stronger fill used for floating navigation.
  static Color glassBar(Brightness brightness) => brightness == Brightness.dark
      ? const Color(0xFF11162B).withValues(alpha: 0.72)
      : Colors.white.withValues(alpha: 0.78);

  static Color glassStroke(Brightness brightness) =>
      brightness == Brightness.dark
      ? Colors.white.withValues(alpha: 0.14)
      : Colors.white.withValues(alpha: 0.88);

  static Color glassShadow(Brightness brightness) =>
      brightness == Brightness.dark
      ? Colors.black.withValues(alpha: 0.42)
      : const Color(0xFF4A5B8C).withValues(alpha: 0.14);
}

const _radius = 24.0;
const _pill = StadiumBorder();
const _seed = ViraPalette.indigo;

ThemeData buildLightTheme({bool compact = false}) =>
    _theme(Brightness.light, compact: compact);

ThemeData buildDarkTheme({bool compact = false}) =>
    _theme(Brightness.dark, compact: compact);

ThemeData _theme(Brightness brightness, {bool compact = false}) {
  final dark = brightness == Brightness.dark;
  final scheme = ColorScheme.fromSeed(seedColor: _seed, brightness: brightness)
      .copyWith(
        surface: dark ? const Color(0xFF0A0E1D) : const Color(0xFFF6F7FE),
        surfaceContainerLowest: dark ? const Color(0xFF0A0E1D) : Colors.white,
        surfaceContainerLow: dark
            ? const Color(0xFF11162B)
            : const Color(0xFFFDFDFF),
        surfaceContainer: dark
            ? const Color(0xFF151B33)
            : const Color(0xFFF1F3FC),
        surfaceContainerHigh: dark
            ? const Color(0xFF1B2240)
            : const Color(0xFFE9ECF9),
        surfaceContainerHighest: dark
            ? const Color(0xFF222A4A)
            : const Color(0xFFE2E6F5),
        primary: dark ? const Color(0xFF8E9BFF) : const Color(0xFF4A5BEF),
        secondary: ViraPalette.violet,
        tertiary: ViraPalette.pink,
        outlineVariant: dark
            ? const Color(0xFF2C3557)
            : const Color(0xFFE3E7F5),
      );
  final base = ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    fontFamily: null,
  );
  final text = base.textTheme.apply(
    bodyColor: scheme.onSurface,
    displayColor: scheme.onSurface,
  );
  return base.copyWith(
    scaffoldBackgroundColor: Colors.transparent,
    canvasColor: Colors.transparent,
    textTheme: text.copyWith(
      displaySmall: text.displaySmall?.copyWith(
        fontSize: compact ? 30 : text.displaySmall?.fontSize,
        fontWeight: FontWeight.w700,
        letterSpacing: -1.6,
      ),
      headlineMedium: text.headlineMedium?.copyWith(
        fontSize: compact ? 26 : text.headlineMedium?.fontSize,
        fontWeight: FontWeight.w700,
        letterSpacing: -1.0,
      ),
      headlineSmall: text.headlineSmall?.copyWith(
        fontSize: compact ? 22 : text.headlineSmall?.fontSize,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.6,
      ),
      titleLarge: text.titleLarge?.copyWith(
        fontSize: compact ? 20 : text.titleLarge?.fontSize,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.3,
      ),
      titleMedium: text.titleMedium?.copyWith(
        fontSize: compact ? 15.5 : text.titleMedium?.fontSize,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.2,
      ),
      titleSmall: text.titleSmall?.copyWith(
        fontSize: compact ? 14 : text.titleSmall?.fontSize,
        fontWeight: FontWeight.w600,
      ),
      bodyLarge: text.bodyLarge?.copyWith(
        fontSize: compact ? 15 : text.bodyLarge?.fontSize,
        height: 1.4,
      ),
      bodyMedium: text.bodyMedium?.copyWith(
        fontSize: compact ? 13.5 : text.bodyMedium?.fontSize,
        height: 1.45,
      ),
      bodySmall: text.bodySmall?.copyWith(
        fontSize: compact ? 12 : text.bodySmall?.fontSize,
        height: 1.35,
      ),
      labelSmall: text.labelSmall?.copyWith(
        fontSize: compact ? 10.5 : text.labelSmall?.fontSize,
      ),
    ),
    splashFactory: InkSparkle.splashFactory,
    visualDensity: VisualDensity.standard,
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        TargetPlatform.android: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.iOS: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.macOS: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.linux: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.windows: FadeForwardsPageTransitionsBuilder(),
      },
    ),
    appBarTheme: AppBarTheme(
      elevation: 0,
      scrolledUnderElevation: 0,
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      foregroundColor: scheme.onSurface,
      centerTitle: false,
      titleTextStyle: text.titleLarge?.copyWith(color: scheme.onSurface),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: ViraPalette.glassFill(brightness),
      surfaceTintColor: Colors.transparent,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(_radius),
        side: BorderSide(color: ViraPalette.glassStroke(brightness)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: dark
          ? Colors.white.withValues(alpha: 0.06)
          : Colors.white.withValues(alpha: 0.72),
      contentPadding: EdgeInsets.symmetric(
        horizontal: compact ? 15 : 18,
        vertical: compact ? 13 : 16,
      ),
      hintStyle: TextStyle(
        color: scheme.onSurfaceVariant.withValues(alpha: 0.7),
      ),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(color: ViraPalette.glassStroke(brightness)),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(color: ViraPalette.glassStroke(brightness)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(
          color: scheme.primary.withValues(alpha: 0.8),
          width: 1.6,
        ),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: BorderSide(color: scheme.error, width: 1.2),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: Size(0, compact ? 46 : 50),
        padding: EdgeInsets.symmetric(
          horizontal: compact ? 20 : 24,
          vertical: compact ? 12 : 14,
        ),
        shape: _pill,
        textStyle: TextStyle(
          fontWeight: FontWeight.w600,
          fontSize: compact ? 14 : 15,
        ),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: Size(0, compact ? 44 : 48),
        padding: EdgeInsets.symmetric(
          horizontal: compact ? 17 : 20,
          vertical: compact ? 11 : 13,
        ),
        shape: _pill,
        side: BorderSide(color: scheme.outlineVariant),
        textStyle: TextStyle(
          fontWeight: FontWeight.w600,
          fontSize: compact ? 13.5 : 14,
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        shape: _pill,
        textStyle: TextStyle(
          fontWeight: FontWeight.w600,
          fontSize: compact ? 13.5 : 14,
        ),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        shape: const CircleBorder(),
        padding: EdgeInsets.all(compact ? 8 : 10),
      ),
    ),
    navigationRailTheme: NavigationRailThemeData(
      backgroundColor: Colors.transparent,
      indicatorColor: scheme.primary.withValues(alpha: dark ? 0.22 : 0.12),
      indicatorShape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
      ),
      selectedIconTheme: IconThemeData(color: scheme.primary),
      selectedLabelTextStyle: TextStyle(
        color: scheme.onSurface,
        fontWeight: FontWeight.w700,
        fontSize: 12,
      ),
      unselectedIconTheme: IconThemeData(color: scheme.onSurfaceVariant),
      unselectedLabelTextStyle: TextStyle(
        color: scheme.onSurfaceVariant,
        fontSize: 12,
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      height: compact ? 60 : 68,
      elevation: 0,
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      indicatorColor: scheme.primary.withValues(alpha: dark ? 0.22 : 0.12),
      indicatorShape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
      ),
      labelTextStyle: WidgetStatePropertyAll(
        TextStyle(
          fontSize: compact ? 10 : 11,
          fontWeight: FontWeight.w600,
          color: scheme.onSurface,
        ),
      ),
    ),
    tabBarTheme: TabBarThemeData(
      dividerColor: Colors.transparent,
      indicatorSize: TabBarIndicatorSize.label,
      indicator: BoxDecoration(
        color: scheme.primary.withValues(alpha: dark ? 0.22 : 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      labelColor: scheme.primary,
      unselectedLabelColor: scheme.onSurfaceVariant,
      labelStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
      unselectedLabelStyle: const TextStyle(
        fontWeight: FontWeight.w500,
        fontSize: 13,
      ),
    ),
    dividerTheme: DividerThemeData(
      color: scheme.outlineVariant.withValues(alpha: 0.5),
      space: 1,
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: dark ? const Color(0xFF1B2240) : const Color(0xFF20263A),
      contentTextStyle: const TextStyle(
        color: Colors.white,
        fontWeight: FontWeight.w500,
      ),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
    ),
    listTileTheme: ListTileThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      contentPadding: EdgeInsets.symmetric(
        horizontal: compact ? 12 : 16,
        vertical: compact ? 2 : 5,
      ),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected) ? Colors.white : null,
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected)
            ? scheme.primary
            : scheme.surfaceContainerHighest,
      ),
      trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
    ),
    chipTheme: ChipThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      side: BorderSide(color: scheme.outlineVariant),
      backgroundColor: dark
          ? Colors.white.withValues(alpha: 0.05)
          : Colors.white.withValues(alpha: 0.6),
      labelStyle: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: dark ? const Color(0xFF12172C) : const Color(0xFFFDFDFF),
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
      titleTextStyle: text.titleLarge?.copyWith(fontWeight: FontWeight.w700),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: dark ? const Color(0xFF12172C) : const Color(0xFFFDFDFF),
      surfaceTintColor: Colors.transparent,
      modalBackgroundColor: dark
          ? const Color(0xFF12172C)
          : const Color(0xFFFDFDFF),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      showDragHandle: true,
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: dark ? const Color(0xFF151B33) : Colors.white,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: scheme.primary,
      linearTrackColor: scheme.surfaceContainerHighest,
    ),
  );
}

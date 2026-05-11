import 'dart:io';
import 'package:image_picker/image_picker.dart';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vibration/vibration.dart';

void main() {
  HttpOverrides.global = MyHttpOverrides();
  runApp(const FlowraDealerApp());
}

class FlowraDealerApp extends StatelessWidget {
  const FlowraDealerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: "Flowra Dealer App",
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF2563EB)),
        scaffoldBackgroundColor: const Color(0xFFF3F5FB),
        useMaterial3: true,
      ),
      home: const SplashScreen(),
    );
  }
}

class AppGradients {
  static const dashboard = LinearGradient(
    colors: [Color(0xFF2563EB), Color(0xFF7C3AED)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const history = LinearGradient(
    colors: [Color(0xFFC2410C), Color(0xFFEA580C)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const wallet = LinearGradient(
    colors: [Color(0xFF2563EB), Color(0xFF7C3AED)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const sets = LinearGradient(
    colors: [Color(0xFF8B3DFF), Color(0xFFA855F7)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const teal = LinearGradient(
    colors: [Color(0xFF0F766E), Color(0xFF0D9488)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );

  static const redemptions = LinearGradient(
    colors: [Color(0xFFBE185D), Color(0xFFDB2777)],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );
}

class MyHttpOverrides extends HttpOverrides {
  @override
  HttpClient createHttpClient(SecurityContext? context) {
    return super.createHttpClient(context)
      ..badCertificateCallback =
          (X509Certificate cert, String host, int port) => true;
  }
}

class ApiService {
  static const String baseUrl = "https://loyalty.flowralive.in";

  static Future<Map<String, String>> _authHeaders({bool json = false}) async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString("dealer_token") ?? "";

    final headers = <String, String>{};
    if (json) headers["Content-Type"] = "application/json";
    if (token.isNotEmpty) headers["Authorization"] = "Bearer $token";
    return headers;
  }

  static String normalizeImageUrl(String value) {
    final v = value.trim();
    if (v.isEmpty) return "";

    if (v.startsWith("http://") || v.startsWith("https://")) {
      return v;
    }

    return "$baseUrl/static/uploads/${v.startsWith("/") ? v.substring(1) : v}";
  }

  static Future<Map<String, dynamic>> dealerLogin(
    String login,
    String password,
  ) async {
    final response = await http.post(
      Uri.parse("$baseUrl/api/dealer/login"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"login": login, "password": password}),
    );
    return _decodeMap(response.body, "Server returned invalid login response");
  }

  static Future<Map<String, dynamic>> dealerLogout(String dealerId) async {
    final response = await http.post(
      Uri.parse("$baseUrl/api/dealer/logout"),
      headers: await _authHeaders(json: true),
      body: jsonEncode({"dealer_id": dealerId}),
    );
    return _decodeMap(response.body, "Server returned invalid logout response");
  }

  static Future<Map<String, dynamic>> getWallet(String dealerId) async {
    final response = await http.get(
      Uri.parse("$baseUrl/api/dealer/wallet/$dealerId"),
      headers: await _authHeaders(),
    );
    return _decodeMap(response.body, "Server returned invalid wallet response");
  }

  static Future<Map<String, dynamic>> scanCoupon(
  String code,
  String dealerId,
) async {
    final response = await http.post(
      Uri.parse(
        "$baseUrl/api/dealer/scan/${Uri.encodeComponent(code)}/$dealerId",
      ),
      headers: await _authHeaders(),
    );
    return _decodeMap(response.body, "Server returned invalid scan response");
  }

  static Future<Map<String, dynamic>> getScannedHistory(
  String dealerId, {
    String? fromDate,
    String? toDate,
  }) async {
    String url = "$baseUrl/api/dealer/scanned-history/$dealerId";

    final queryParams = <String, String>{};
    if (fromDate != null && fromDate.isNotEmpty) {
      queryParams["from_date"] = fromDate;
    }
    if (toDate != null && toDate.isNotEmpty) {
      queryParams["to_date"] = toDate;
    }

    if (queryParams.isNotEmpty) {
      final uri = Uri.parse(url).replace(queryParameters: queryParams);
      url = uri.toString();
    }

    final response = await http.get(
      Uri.parse(url),
      headers: await _authHeaders(),
    );
    return _decodeMap(
      response.body,
      "Server returned invalid history response",
    );
  }

  static Future<Map<String, dynamic>> getSets(String dealerId) async {
    final response = await http.get(
      Uri.parse("$baseUrl/api/dealer/sets/$dealerId"),
      headers: await _authHeaders(),
    );
    return _decodeMap(response.body, "Server returned invalid sets response");
  }

  static Future<Map<String, dynamic>> getRedemptionHistory(String dealerId) async {
    final response = await http.get(
      Uri.parse("$baseUrl/api/dealer/redemption-history/$dealerId"),
      headers: await _authHeaders(),
    );
    return _decodeMap(
      response.body,
      "Server returned invalid redemption history response",
    );
  }

  static Future<List<dynamic>> getDealerBanners(String dealerId) async {
    final response = await http.get(
      Uri.parse("$baseUrl/api/dealer/banners/$dealerId"),
      headers: await _authHeaders(),
    );
    final data = _decodeMap(
      response.body,
      "Server returned invalid banners response",
    );
    if (data["success"] == true) {
      return data["banners"] ?? [];
    }
    return [];
  }

  static Future<Map<String, dynamic>> uploadDealerProfileImage(
  String dealerId,
    File imageFile,
  ) async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString("dealer_token") ?? "";

    final request = http.MultipartRequest(
      "POST",
      Uri.parse("$baseUrl/api/dealer/upload-profile-image/$dealerId"),
    );

    if (token.isNotEmpty) {
      request.headers["Authorization"] = "Bearer $token";
    }

    request.files.add(
      await http.MultipartFile.fromPath("profile_image", imageFile.path),
    );

    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);

    return _decodeMap(
      response.body,
      "Server returned invalid profile image upload response",
    );
  }

  static Map<String, dynamic> _decodeMap(String rawBody, String errorMessage) {
    final body = rawBody.trim();
    if (body.startsWith("<!DOCTYPE html>") || body.startsWith("<html")) {
      throw Exception(errorMessage);
    }
    final decoded = jsonDecode(body);
    if (decoded is Map<String, dynamic>) return decoded;
    throw Exception(errorMessage);
  }
  static Future<Map<String, dynamic>> requestSetRedemption(
  String dealerId,
  String setKey,
) async {
  final response = await http.post(
    Uri.parse("$baseUrl/api/dealer/request-set-redemption"),
    headers: await _authHeaders(json: true),
    body: jsonEncode({
      "dealer_id": dealerId,
      "set_key": setKey,
    }),
  );

  return _decodeMap(
    response.body,
    "Server returned invalid redemption request response",
  );
}


}

class ScanFeedbackService {
  static const MethodChannel _channel = MethodChannel('flowra_scan_feedback');

  static Future<void> success() async {
    try {
      await _channel.invokeMethod('successBeep');
    } catch (_) {}
    await _vibrateSuccess();
  }

  static Future<void> error() async {
    try {
      await _channel.invokeMethod('errorBeep');
    } catch (_) {}
    await _vibrateError();
  }

  static Future<void> _vibrateSuccess() async {
    try {
      final hasVibrator = await Vibration.hasVibrator();
      if (hasVibrator == true) {
        await Vibration.vibrate(duration: 120);
      }
    } catch (_) {}
  }

  static Future<void> _vibrateError() async {
    try {
      final hasVibrator = await Vibration.hasVibrator();
      if (hasVibrator == true) {
        await Vibration.vibrate(pattern: [0, 120, 80, 180]);
      }
    } catch (_) {}
  }
}

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _scale;
  late Animation<double> _opacity;

  @override
  void initState() {
    super.initState();

    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    );

    _scale = Tween<double>(
      begin: 0.6,
      end: 1.0,
    ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeOutBack));

    _opacity = Tween<double>(
      begin: 0.0,
      end: 1.0,
    ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeIn));

    _controller.forward();
    goNext();
  }

  Future<void> goNext() async {
    final prefs = await SharedPreferences.getInstance();
    final dealerId = prefs.getString("dealer_id");

    await Future.delayed(const Duration(seconds: 2));
    if (!mounted) return;

    if (dealerId != null) {
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const DashboardLoader()),
      );
    } else {
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const LoginScreen()),
      );
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppGradients.dashboard),
        child: Center(
          child: FadeTransition(
            opacity: _opacity,
            child: ScaleTransition(
              scale: _scale,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: Colors.white.withValues(alpha: 0.30),
                          blurRadius: 30,
                          spreadRadius: 4,
                        ),
                      ],
                    ),
                    child: const Icon(
                      Icons.local_offer,
                      size: 48,
                      color: Color(0xFF2563EB),
                    ),
                  ),
                  const SizedBox(height: 18),
                  const Text(
                    "FLOWRA",
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 34,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 1.2,
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    "Dealer Application",
                    style: TextStyle(color: Colors.white70, fontSize: 16),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class DashboardLoader extends StatefulWidget {
  const DashboardLoader({super.key});

  @override
  State<DashboardLoader> createState() => _DashboardLoaderState();
}

class _DashboardLoaderState extends State<DashboardLoader> {
  @override
  void initState() {
    super.initState();
    loadDealer();
  }

  Future<void> loadDealer() async {
    final prefs = await SharedPreferences.getInstance();
    final dealer = {
      "id": prefs.getString("dealer_id"),
      "dealer_code": prefs.getString("dealer_code"),
      "name": prefs.getString("dealer_name"),
      "mobile": prefs.getString("dealer_mobile"),
      "email": prefs.getString("dealer_email"),
      "city": prefs.getString("dealer_city"),
      "state": prefs.getString("dealer_state"),
      "gst": prefs.getString("dealer_gst"),
      "pan": prefs.getString("dealer_pan"),
      "address": prefs.getString("dealer_address"),
      "profile_image": prefs.getString("dealer_profile_image"),
    };

    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (_) => DashboardScreen(dealer: dealer)),
    );
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: Center(child: CircularProgressIndicator()));
  }
}

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final loginController = TextEditingController();
  final passwordController = TextEditingController();
  bool loading = false;

  Future<void> login() async {
    if (loginController.text.trim().isEmpty ||
        passwordController.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Please enter email/phone and password")),
      );
      return;
    }

    setState(() => loading = true);

    try {
      final data = await ApiService.dealerLogin(
        loginController.text.trim(),
        passwordController.text.trim(),
      );

      if (!mounted) return;

      if (data["success"] == true) {
        final dealer = data["dealer"] ?? {};

        final prefs = await SharedPreferences.getInstance();
        await prefs.setString("dealer_id", dealer["id"].toString());
        await prefs.setString("dealer_code", dealer["dealer_code"] ?? "");
        await prefs.setString("dealer_name", dealer["name"] ?? "");
        await prefs.setString("dealer_mobile", dealer["mobile"] ?? "");
        await prefs.setString("dealer_email", dealer["email"] ?? "");
        await prefs.setString("dealer_city", dealer["city"] ?? "");
        await prefs.setString("dealer_state", dealer["state"] ?? "");
        await prefs.setString("dealer_gst", dealer["gst"] ?? "");
        await prefs.setString("dealer_pan", dealer["pan"] ?? "");
        await prefs.setString("dealer_address", dealer["address"] ?? "");
        await prefs.setString(
          "dealer_profile_image",
          dealer["profile_image"] ?? "",
        );
        await prefs.setString("dealer_token", data["token"] ?? "");

        if (!mounted) return;
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(builder: (_) => DashboardScreen(dealer: dealer)),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data["message"] ?? "Login failed")),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text("Connection error: $e")));
    }

    if (mounted) setState(() => loading = false);
  }

  @override
  void dispose() {
    loginController.dispose();
    passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(gradient: AppGradients.dashboard),
        child: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Card(
                elevation: 12,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(24),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: SizedBox(
                    width: 380,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const CircleAvatar(
                          radius: 34,
                          backgroundColor: Color(0xFFEFF6FF),
                          child: Icon(
                            Icons.storefront,
                            size: 34,
                            color: Color(0xFF2563EB),
                          ),
                        ),
                        const SizedBox(height: 14),
                        const Text(
                          "FLOWRA Dealer Login",
                          style: TextStyle(
                            fontSize: 24,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const SizedBox(height: 24),
                        TextField(
                          controller: loginController,
                          decoration: const InputDecoration(
                            labelText: "Email or Phone",
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 14),
                        TextField(
                          controller: passwordController,
                          obscureText: true,
                          decoration: const InputDecoration(
                            labelText: "Password",
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 20),
                        SizedBox(
                          width: double.infinity,
                          height: 52,
                          child: ElevatedButton(
                            onPressed: loading ? null : login,
                            child:
                                loading
                                    ? const SizedBox(
                                      width: 22,
                                      height: 22,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                        color: Colors.white,
                                      ),
                                    )
                                    : const Text("Login"),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class DashboardScreen extends StatefulWidget {
  final Map dealer;
  const DashboardScreen({super.key, required this.dealer});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  List banners = [];
  bool bannerLoading = true;

  @override
  void initState() {
    super.initState();
    loadBanners();
  }

  Future<void> loadBanners() async {
    try {
      final data = await ApiService.getDealerBanners(widget.dealer["id"].toString());
      if (!mounted) return;
      setState(() {
        banners = data;
        bannerLoading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        banners = [];
        bannerLoading = false;
      });
    }
  }

  Future<void> logout(BuildContext context) async {
    final prefs = await SharedPreferences.getInstance();
    final dealerId = prefs.getString("dealer_id");

    try {
      if (dealerId != null) {
        await ApiService.dealerLogout(dealerId);
      }
    } catch (_) {}

    await prefs.clear();

    if (!context.mounted) return;
    Navigator.pushAndRemoveUntil(
      context,
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (route) => false,
    );
  }

  Widget bannerSection() {
    if (bannerLoading) {
      return const SizedBox(
        height: 160,
        child: Center(child: CircularProgressIndicator()),
      );
    }

    if (banners.isEmpty) return const SizedBox.shrink();

    final banner = banners.first as Map;
    final imageUrl = (banner["image_url"] ?? "").toString();
    final title = (banner["title"] ?? "").toString();

    return Container(
      height: 160,
      width: double.infinity,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.12),
            blurRadius: 10,
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(18),
        child: Stack(
          fit: StackFit.expand,
          children: [
            Image.network(
              imageUrl,
              fit: BoxFit.cover,
              errorBuilder: (context, error, stackTrace) {
                return Container(
                  color: Colors.grey.shade300,
                  alignment: Alignment.center,
                  child: const Text(
                    "Banner not available",
                    style: TextStyle(
                      color: Colors.black54,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                );
              },
            ),
            Container(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.bottomCenter,
                  end: Alignment.topCenter,
                  colors: [
                    Colors.black.withValues(alpha: 0.50),
                    Colors.transparent,
                  ],
                ),
              ),
            ),
            if (title.isNotEmpty)
              Positioned(
                left: 12,
                right: 12,
                bottom: 12,
                child: Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 15,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _profileHeader(BuildContext context) {
    final dealerName = (widget.dealer["name"] ?? "Dealer").toString();
    final city =
        (widget.dealer["city"] == null ||
                widget.dealer["city"].toString().trim().isEmpty)
            ? "Not Available"
            : widget.dealer["city"].toString();

    final profileImage =
        (widget.dealer["profile_image"] ?? "").toString().trim();

    return InkWell(
      borderRadius: BorderRadius.circular(24),
      onTap: () {
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => DealerProfileScreen(dealer: widget.dealer),
          ),
        );
      },
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          gradient: AppGradients.dashboard,
          borderRadius: BorderRadius.circular(24),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.10),
              blurRadius: 18,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: Row(
          children: [
            CircleAvatar(
              radius: 30,
              backgroundColor: Colors.white.withValues(alpha: 0.20),
              backgroundImage:
                  profileImage.isNotEmpty ? NetworkImage(profileImage) : null,
              child:
                  profileImage.isEmpty
                      ? const Icon(Icons.person, color: Colors.white, size: 30)
                      : null,
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    "Welcome, $dealerName 👋",
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 21,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    city,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.92),
                      fontSize: 15,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    "Tap to view profile",
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.85),
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
              ),
            ),
            const Icon(Icons.arrow_forward_ios, color: Colors.white, size: 18),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final dashboardItems = [
      {
        "title": "Scan Coupon",
        "subtitle": "Scan and add points",
        "icon": Icons.qr_code_scanner,
        "colors": const [Color(0xFF0F4CDE), Color(0xFF2563EB)],
        "page": ScanScreen(dealer: widget.dealer),
      },
      {
        "title": "Wallet",
        "subtitle": "View total points",
        "icon": Icons.account_balance_wallet,
        "colors": const [Color(0xFF047857), Color(0xFF059669)],
        "page": WalletScreen(dealer: widget.dealer),
      },
      {
        "title": "History",
        "subtitle": "Scanned coupons",
        "icon": Icons.history,
        "colors": const [Color(0xFFC2410C), Color(0xFFEA580C)],
        "page": HistoryScreen(dealer: widget.dealer),
      },
      {
        "title": "Coupon Sets",
        "subtitle": "Track sets of 10",
        "icon": Icons.inventory_2,
        "colors": const [Color(0xFF6D28D9), Color(0xFF7C3AED)],
        "page": SetSummaryScreen(dealer: widget.dealer),
      },
      {
        "title": "Redemptions",
        "subtitle": "Redemption history",
        "icon": Icons.receipt_long,
        "colors": const [Color(0xFFBE185D), Color(0xFFDB2777)],
        "page": RedemptionHistoryScreen(dealer: widget.dealer),
      },
      {
        "title": "About Us",
        "subtitle": "Know our company",
        "icon": Icons.info_outline,
        "colors": const [Color(0xFF0F766E), Color(0xFF0D9488)],
        "page": const AboutUsScreen(),
      },
    ];

    return Scaffold(
      appBar: AppBar(
        elevation: 0,
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
        title: const Text(
          "FLOWRA Dealer Panel",
          style: TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
        ),
        flexibleSpace: Container(
          decoration: const BoxDecoration(gradient: AppGradients.dashboard),
        ),
        actions: [
          IconButton(
            onPressed: () => logout(context),
            icon: const Icon(Icons.logout, color: Colors.white),
          ),
        ],
      ),
      body: Container(
        decoration: BoxDecoration(
          color: const Color(0xFFF3F5FB),
          gradient: LinearGradient(
            colors: [
              Colors.white,
              const Color(0xFFEEF2FF).withValues(alpha: 0.80),
            ],
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              _profileHeader(context),
              const SizedBox(height: 18),
              bannerSection(),
              const SizedBox(height: 18),
              Expanded(
                child: GridView.builder(
                  itemCount: dashboardItems.length,
                  gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 2,
                    crossAxisSpacing: 14,
                    mainAxisSpacing: 14,
                    mainAxisExtent: 220,
                  ),
                  itemBuilder: (context, index) {
                    final item = dashboardItems[index];
                    return _animatedMenuCard(
                      context,
                      title: item["title"] as String,
                      subtitle: item["subtitle"] as String,
                      icon: item["icon"] as IconData,
                      colors: item["colors"] as List<Color>,
                      page: item["page"] as Widget,
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _animatedMenuCard(
    BuildContext context, {
    required String title,
    required String subtitle,
    required IconData icon,
    required List<Color> colors,
    required Widget page,
  }) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(24),
        onTap: () {
          Navigator.push(context, MaterialPageRoute(builder: (_) => page));
        },
        child: Container(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: colors,
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            borderRadius: BorderRadius.circular(24),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.12),
                blurRadius: 14,
                offset: const Offset(0, 6),
              ),
            ],
          ),
          child: Container(
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: Colors.white.withValues(alpha: 0.10)),
            ),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.black.withValues(alpha: 0.18),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Icon(icon, size: 26, color: Colors.white),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.w800,
                      height: 1.1,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    subtitle,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.92),
                      fontSize: 12,
                      fontWeight: FontWeight.w500,
                      height: 1.1,
                    ),
                  ),
                  const Spacer(),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 7,
                    ),
                    decoration: BoxDecoration(
                      color: Colors.black.withValues(alpha: 0.22),
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: const Text(
                      "Open",
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                        fontSize: 12,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class DealerProfileScreen extends StatefulWidget {
  final Map dealer;
  const DealerProfileScreen({super.key, required this.dealer});

  @override
  State<DealerProfileScreen> createState() => _DealerProfileScreenState();
}

class _DealerProfileScreenState extends State<DealerProfileScreen> {
  late Map dealer;
  bool uploading = false;
  final ImagePicker _picker = ImagePicker();

  @override
  void initState() {
    super.initState();
    dealer = Map<String, dynamic>.from(widget.dealer);
  }

  Future<void> _pickAndUploadImage() async {
    final XFile? pickedFile = await _picker.pickImage(
      source: ImageSource.gallery,
      imageQuality: 75,
    );

    if (pickedFile == null) return;
    if (!mounted) return;

    setState(() => uploading = true);

    try {
      final file = File(pickedFile.path);

      final data = await ApiService.uploadDealerProfileImage(
        dealer["id"].toString(),
        file,
      );

      if (!mounted) return;

      if (data["success"] == true) {
        final imageUrl = (data["profile_image"] ?? "").toString();

        dealer["profile_image"] = imageUrl;

        final prefs = await SharedPreferences.getInstance();
        await prefs.setString("dealer_profile_image", imageUrl);

        if (!mounted) return;

        setState(() {});

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data["message"] ?? "Profile image updated")),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data["message"] ?? "Upload failed")),
        );
      }
    } catch (e) {
      if (!mounted) return;

      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text("Upload error: $e")));
    } finally {
      if (mounted) {
        setState(() => uploading = false);
      }
    }
  }

  Widget _infoTile({
    required IconData icon,
    required String label,
    required String value,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.06),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: const Color(0xFF2563EB)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: const TextStyle(
                    fontSize: 13,
                    color: Colors.black54,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  value.trim().isEmpty ? "-" : value,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: Colors.black87,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final profileImage = (dealer["profile_image"] ?? "").toString().trim();

    return Scaffold(
      appBar: AppBar(
        title: const Text("My Profile"),
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
        flexibleSpace: Container(
          decoration: const BoxDecoration(gradient: AppGradients.dashboard),
        ),
      ),
      body: Container(
        decoration: BoxDecoration(
          color: const Color(0xFFF3F5FB),
          gradient: LinearGradient(
            colors: [
              Colors.white,
              const Color(0xFFEEF2FF).withValues(alpha: 0.80),
            ],
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
          ),
        ),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  gradient: AppGradients.dashboard,
                  borderRadius: BorderRadius.circular(24),
                ),
                child: Column(
                  children: [
                    Stack(
                      children: [
                        CircleAvatar(
                          radius: 50,
                          backgroundColor: Colors.white.withValues(alpha: 0.20),
                          backgroundImage:
                              profileImage.isNotEmpty
                                  ? NetworkImage(profileImage)
                                  : null,
                          child:
                              profileImage.isEmpty
                                  ? const Icon(
                                    Icons.person,
                                    size: 45,
                                    color: Colors.white,
                                  )
                                  : null,
                        ),
                        Positioned(
                          right: 0,
                          bottom: 0,
                          child: InkWell(
                            onTap: uploading ? null : _pickAndUploadImage,
                            child: Container(
                              padding: const EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: Colors.white,
                                shape: BoxShape.circle,
                                border: Border.all(
                                  color: const Color(0xFF2563EB),
                                  width: 2,
                                ),
                              ),
                              child:
                                  uploading
                                      ? const SizedBox(
                                        width: 18,
                                        height: 18,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                        ),
                                      )
                                      : const Icon(
                                        Icons.camera_alt,
                                        size: 18,
                                        color: Color(0xFF2563EB),
                                      ),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text(
                      (dealer["name"] ?? "Dealer").toString(),
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 22,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      (dealer["email"] ?? "").toString(),
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.92),
                        fontSize: 14,
                      ),
                    ),
                    const SizedBox(height: 10),
                    Text(
                      "Tap camera icon to update photo",
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.92),
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              _infoTile(
                icon: Icons.person_outline,
                label: "Name",
                value: (dealer["name"] ?? "").toString(),
              ),
              _infoTile(
                icon: Icons.email_outlined,
                label: "Gmail",
                value: (dealer["email"] ?? "").toString(),
              ),
              _infoTile(
                icon: Icons.phone_outlined,
                label: "Mobile",
                value: (dealer["mobile"] ?? "").toString(),
              ),
              _infoTile(
                icon: Icons.receipt_long_outlined,
                label: "GST Number",
                value: (dealer["gst"] ?? "").toString(),
              ),
              _infoTile(
                icon: Icons.badge_outlined,
                label: "PAN Number",
                value: (dealer["pan"] ?? "").toString(),
              ),
              _infoTile(
                icon: Icons.location_on_outlined,
                label: "Address",
                value: (dealer["address"] ?? "").toString(),
              ),
              _infoTile(
                icon: Icons.location_city_outlined,
                label: "City",
                value: (dealer["city"] ?? "").toString(),
              ),
              _infoTile(
                icon: Icons.map_outlined,
                label: "State",
                value: (dealer["state"] ?? "").toString(),
              ),
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                height: 50,
                child: ElevatedButton(
                  onPressed: () {
                    Navigator.pop(context, dealer);
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF2563EB),
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                  ),
                  child: const Text(
                    "Back to Dashboard",
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class ScanScreen extends StatefulWidget {
  final Map dealer;
  const ScanScreen({super.key, required this.dealer});

  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen>
    with SingleTickerProviderStateMixin {
  bool processing = false;
  String result = "Scan a coupon";
  bool scanSuccess = false;
  bool showScanAnimation = false;
  late AnimationController _animationController;
  late Animation<double> _scaleAnimation;
  final MobileScannerController cameraController = MobileScannerController();
  final TextEditingController manualCodeController = TextEditingController();

  @override
  void initState() {
    super.initState();

    _animationController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 450),
    );

    _scaleAnimation = Tween<double>(begin: 0.6, end: 1.0).animate(
      CurvedAnimation(parent: _animationController, curve: Curves.easeOutBack),
    );
  }

  @override
  void dispose() {
    _animationController.dispose();
    cameraController.dispose();
    manualCodeController.dispose();
    super.dispose();
  }

  String extractCouponCode(String raw) {
    final value = raw.trim();
    if (value.contains("/scan/")) {
      return value.split("/scan/").last.trim().toUpperCase();
    }
    return value.toUpperCase();
  }

  Future<void> _showAnimatedResult({required bool success}) async {
    if (!mounted) return;

    setState(() {
      scanSuccess = success;
      showScanAnimation = true;
    });

    _animationController.reset();
    _animationController.forward();

    await Future.delayed(const Duration(milliseconds: 900));

    if (!mounted) return;

    setState(() {
      showScanAnimation = false;
    });
  }

  Future<void> onScan(String code) async {
    if (processing) return;

    final cleanedCode = code.trim().toUpperCase();
    if (cleanedCode.isEmpty) return;

    setState(() {
      processing = true;
      result = "Processing coupon...";
    });

    try {
      final data = await ApiService.scanCoupon(
        cleanedCode,
        widget.dealer["id"],
      );

      if (!mounted) return;

      final message = (data["message"] ?? "Done").toString();
      final success = data["success"] == true;

      setState(() {
        result = message;
      });

      if (success) {
        manualCodeController.clear();
        await ScanFeedbackService.success();
      } else {
        await ScanFeedbackService.error();
      }

      await _showAnimatedResult(success: success);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        result = "Error: $e";
      });
      await ScanFeedbackService.error();
      await _showAnimatedResult(success: false);
    }

    if (mounted) {
      await Future.delayed(const Duration(milliseconds: 700));
      setState(() {
        processing = false;
      });
    }
  }

  Future<void> submitManualCode() async {
    final code = manualCodeController.text.trim().toUpperCase();

    if (code.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text("Please enter coupon code")));
      return;
    }

    await onScan(code);
  }

  Widget _scannerOverlay() {
    return IgnorePointer(
      child: AnimatedOpacity(
        opacity: showScanAnimation ? 1 : 0,
        duration: const Duration(milliseconds: 180),
        child: Container(
          color: Colors.black.withValues(alpha: 0.20),
          child: Center(
            child: ScaleTransition(
              scale: _scaleAnimation,
              child: Container(
                width: 110,
                height: 110,
                decoration: BoxDecoration(
                  color:
                      scanSuccess
                          ? Colors.green.withValues(alpha: 0.92)
                          : Colors.red.withValues(alpha: 0.92),
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.20),
                      blurRadius: 18,
                      offset: const Offset(0, 8),
                    ),
                  ],
                ),
                child: Icon(
                  scanSuccess ? Icons.check_rounded : Icons.close_rounded,
                  color: Colors.white,
                  size: 54,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _scanFrame() {
    return Center(
      child: Container(
        width: 250,
        height: 250,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(24),
          border: Border.all(
            color: Colors.white.withValues(alpha: 0.90),
            width: 3,
          ),
        ),
        child: Stack(
          children: [
            Positioned(top: 0, left: 0, child: _corner()),
            Positioned(top: 0, right: 0, child: _corner(isRight: true)),
            Positioned(bottom: 0, left: 0, child: _corner(isBottom: true)),
            Positioned(
              bottom: 0,
              right: 0,
              child: _corner(isRight: true, isBottom: true),
            ),
          ],
        ),
      ),
    );
  }

  Widget _corner({bool isRight = false, bool isBottom = false}) {
    return Container(
      width: 42,
      height: 42,
      decoration: BoxDecoration(
        border: Border(
          top:
              isBottom
                  ? BorderSide.none
                  : const BorderSide(color: Colors.white, width: 5),
          bottom:
              isBottom
                  ? const BorderSide(color: Colors.white, width: 5)
                  : BorderSide.none,
          left:
              isRight
                  ? BorderSide.none
                  : const BorderSide(color: Colors.white, width: 5),
          right:
              isRight
                  ? const BorderSide(color: Colors.white, width: 5)
                  : BorderSide.none,
        ),
        borderRadius: BorderRadius.only(
          topLeft:
              !isRight && !isBottom ? const Radius.circular(18) : Radius.zero,
          topRight:
              isRight && !isBottom ? const Radius.circular(18) : Radius.zero,
          bottomLeft:
              !isRight && isBottom ? const Radius.circular(18) : Radius.zero,
          bottomRight:
              isRight && isBottom ? const Radius.circular(18) : Radius.zero,
        ),
      ),
    );
  }

  Widget _manualEntrySection() {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "QR damaged? Enter manual code",
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: manualCodeController,
            textCapitalization: TextCapitalization.characters,
            inputFormatters: [
              FilteringTextInputFormatter.allow(RegExp(r'[A-Za-z0-9]')),
              LengthLimitingTextInputFormatter(32),
            ],
            decoration: InputDecoration(
              hintText: "Enter coupon code",
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(14),
              ),
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 14,
                vertical: 12,
              ),
            ),
            onChanged: (value) {
              final upper = value.toUpperCase();
              if (value != upper) {
                manualCodeController.value = manualCodeController.value
                    .copyWith(
                      text: upper,
                      selection: TextSelection.collapsed(offset: upper.length),
                    );
              }
            },
            onSubmitted: (_) {
              if (!processing) submitManualCode();
            },
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            height: 48,
            child: ElevatedButton.icon(
              onPressed: processing ? null : submitManualCode,
              icon: const Icon(Icons.keyboard),
              label: const Text("Redeem by Code"),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Scan Coupon"),
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
        flexibleSpace: Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              colors: [Color(0xFF1D4ED8), Color(0xFF3B82F6)],
            ),
          ),
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: Stack(
              fit: StackFit.expand,
              children: [
                MobileScanner(
                  controller: cameraController,
                  onDetect: (capture) {
                    final barcodes = capture.barcodes;
                    if (barcodes.isNotEmpty && !processing) {
                      final rawValue = barcodes.first.rawValue;
                      if (rawValue != null && rawValue.isNotEmpty) {
                        final cleanedCode = extractCouponCode(rawValue);
                        onScan(cleanedCode);
                      }
                    }
                  },
                ),
                _scanFrame(),
                _scannerOverlay(),
              ],
            ),
          ),
          Container(
            width: double.infinity,
            margin: const EdgeInsets.all(16),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors:
                    showScanAnimation
                        ? (scanSuccess
                            ? const [Color(0xFF16A34A), Color(0xFF22C55E)]
                            : const [Color(0xFFDC2626), Color(0xFFEF4444)])
                        : const [Color(0xFF2563EB), Color(0xFF7C3AED)],
              ),
              borderRadius: BorderRadius.circular(18),
            ),
            child: Text(
              result,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: Colors.white,
              ),
              textAlign: TextAlign.center,
            ),
          ),
          _manualEntrySection(),
        ],
      ),
    );
  }
}

class WalletScreen extends StatefulWidget {
  final Map dealer;
  const WalletScreen({super.key, required this.dealer});

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  int totalPoints = 0;
  List partPoints = [];
  bool loading = true;

  @override
  void initState() {
    super.initState();
    loadWallet();
  }

  Future<void> loadWallet() async {
    try {
      final data = await ApiService.getWallet(widget.dealer["id"]);
      if (!mounted) return;

      setState(() {
        totalPoints = int.tryParse("${data["total_points"] ?? 0}") ?? 0;
        partPoints = data["part_points"] ?? [];
        loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        loading = false;
      });
    }
  }

  Widget totalPointsCard() {
    return InkWell(
      borderRadius: BorderRadius.circular(26),
      onTap: () {
        Navigator.push(
          context,
          MaterialPageRoute(
            builder:
                (_) => WalletDetailsScreen(
                  totalPoints: totalPoints,
                  partPoints: partPoints,
                ),
          ),
        );
      },
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(22),
        decoration: BoxDecoration(
          gradient: AppGradients.wallet,
          borderRadius: BorderRadius.circular(26),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.12),
              blurRadius: 14,
              offset: const Offset(0, 6),
            ),
          ],
        ),
        child: Column(
          children: [
            const Text(
              "Total Points",
              style: TextStyle(color: Colors.white70, fontSize: 15),
            ),
            const SizedBox(height: 8),
            Text(
              "$totalPoints",
              style: const TextStyle(
                color: Colors.white,
                fontSize: 34,
                fontWeight: FontWeight.w800,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget partCard(Map item) {
    final partNo = (item["part_no"] ?? "-").toString();
    final points = item["points"] ?? 0;

    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF5F5FA),
        borderRadius: BorderRadius.circular(20),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            width: 54,
            height: 54,
            decoration: BoxDecoration(
              color: const Color(0xFFE9F2FF),
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Icon(
              Icons.qr_code_2,
              color: Color(0xFF2563EB),
              size: 26,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  "Part No: $partNo",
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 16,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  "Points: $points",
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 15,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Scanned Part Points"),
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
        flexibleSpace: Container(
          decoration: const BoxDecoration(gradient: AppGradients.wallet),
        ),
      ),
      body:
          loading
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                onRefresh: loadWallet,
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    totalPointsCard(),
                    if (partPoints.isEmpty)
                      const Padding(
                        padding: EdgeInsets.only(top: 30),
                        child: Center(child: Text("No points found")),
                      )
                    else
                      ...partPoints.map((e) => partCard(e as Map)),
                  ],
                ),
              ),
    );
  }
}

class WalletDetailsScreen extends StatelessWidget {
  final int totalPoints;
  final List partPoints;

  const WalletDetailsScreen({
    super.key,
    required this.totalPoints,
    required this.partPoints,
  });

  Widget partCard(Map item) {
    final partNo = (item["part_no"] ?? "-").toString();
    final points = item["points"] ?? 0;

    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF5F5FA),
        borderRadius: BorderRadius.circular(20),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            width: 54,
            height: 54,
            decoration: BoxDecoration(
              color: const Color(0xFFE9F2FF),
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Icon(
              Icons.qr_code_2,
              color: Color(0xFF2563EB),
              size: 26,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  "Part No: $partNo",
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 16,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  "Points: $points",
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 15,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Scanned Part Points"),
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
        flexibleSpace: Container(
          decoration: const BoxDecoration(gradient: AppGradients.wallet),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(22),
            decoration: BoxDecoration(
              gradient: AppGradients.wallet,
              borderRadius: BorderRadius.circular(26),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.12),
                  blurRadius: 14,
                  offset: const Offset(0, 6),
                ),
              ],
            ),
            child: Column(
              children: [
                const Text(
                  "Total Points",
                  style: TextStyle(color: Colors.white70, fontSize: 15),
                ),
                const SizedBox(height: 8),
                Text(
                  "$totalPoints",
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 34,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
          ),
          if (partPoints.isEmpty)
            const Padding(
              padding: EdgeInsets.only(top: 30),
              child: Center(child: Text("No points found")),
            )
          else
            ...partPoints.map((e) => partCard(e as Map)),
        ],
      ),
    );
  }
}

class HistoryScreen extends StatefulWidget {
  final Map dealer;
  const HistoryScreen({super.key, required this.dealer});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  List history = [];
  bool loading = true;
  DateTime? fromDate;
  DateTime? toDate;

  @override
  void initState() {
    super.initState();
    // no default filter
    loadHistory();
  }

  String formatDate(DateTime date) {
    final y = date.year.toString().padLeft(4, '0');
    final m = date.month.toString().padLeft(2, '0');
    final d = date.day.toString().padLeft(2, '0');
    return "$y-$m-$d";
  }

  Future<void> loadHistory() async {
    setState(() => loading = true);

    try {
      final data = await ApiService.getScannedHistory(
        widget.dealer["id"],
        fromDate: fromDate != null ? formatDate(fromDate!) : null,
        toDate: toDate != null ? formatDate(toDate!) : null,
      );

      if (!mounted) return;
      setState(() {
        history = data["history"] ?? [];
        loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => loading = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text("Failed to load history: $e")));
    }
  }

  Future<void> pickFromDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: fromDate ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
    );
    if (picked != null) {
      setState(() => fromDate = picked);
    }
  }

  Future<void> pickToDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: toDate ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
    );
    if (picked != null) {
      setState(() => toDate = picked);
    }
  }

  void clearFilters() {
    setState(() {
      fromDate = null;
      toDate = null;
    });
    loadHistory();
  }

  Widget _dateButton(String label, VoidCallback onTap) {
    return Expanded(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(22),
        child: Container(
          height: 56,
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.92),
            borderRadius: BorderRadius.circular(22),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.12),
                blurRadius: 6,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(
                Icons.calendar_today_outlined,
                size: 20,
                color: Color(0xFF6B7280),
              ),
              const SizedBox(width: 10),
              Flexible(
                child: Text(
                  label,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                    color: Color(0xFF4B5563),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget filterCard() {
    return Container(
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFF2563EB), Color(0xFF9333EA)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(26),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.10),
            blurRadius: 14,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.filter_alt, color: Colors.white, size: 24),
              SizedBox(width: 10),
              Text(
                "Filter History",
                style: TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w800,
                  fontSize: 18,
                ),
              ),
            ],
          ),
          const SizedBox(height: 18),
          Row(
            children: [
              _dateButton(
                fromDate == null ? "From Date" : formatDate(fromDate!),
                pickFromDate,
              ),
              const SizedBox(width: 12),
              _dateButton(
                toDate == null ? "To Date" : formatDate(toDate!),
                pickToDate,
              ),
            ],
          ),
          const SizedBox(height: 18),
          SizedBox(
            width: double.infinity,
            height: 54,
            child: ElevatedButton(
              onPressed: loadHistory,
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.white.withValues(alpha: 0.92),
                foregroundColor: const Color(0xFF4B5563),
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(22),
                ),
              ),
              child: const Text(
                "Apply Filter",
                style: TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
              ),
            ),
          ),
          const SizedBox(height: 10),
          TextButton.icon(
            onPressed: clearFilters,
            style: TextButton.styleFrom(foregroundColor: Colors.white),
            icon: const Icon(Icons.clear),
            label: const Text(
              "Clear",
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }

  Widget historyItem(Map item) {
    final productName = (item["product_name"] ?? "-").toString();
    final partNo = (item["part_no"] ?? "-").toString();
    final code = (item["code"] ?? "-").toString();
    final points = item["points"] ?? 0;
    final status = (item["status"] ?? "").toString().toLowerCase();
    final scannedAt = (item["scanned_at"] ?? "-").toString();

    final statusColor =
        status == "redeemed"
            ? const Color(0xFFDB2777)
            : const Color(0xFF16A34A);
    final statusText = status.isEmpty ? "NA" : status.toUpperCase();

    return Container(
      margin: const EdgeInsets.only(top: 16),
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        color: const Color(0xFFF5F5FA),
        borderRadius: BorderRadius.circular(24),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(top: 2),
            child: Icon(Icons.history, color: Color(0xFF2563EB), size: 26),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        code,
                        style: const TextStyle(
                          fontWeight: FontWeight.w800,
                          fontSize: 16,
                        ),
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: statusColor.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text(
                        statusText,
                        style: TextStyle(
                          color: statusColor,
                          fontWeight: FontWeight.w800,
                          fontSize: 13,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Text(
                  "Part No: $partNo",
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  "Product: $productName",
                  style: const TextStyle(fontSize: 16),
                ),
                const SizedBox(height: 4),
                Text("Points: $points", style: const TextStyle(fontSize: 16)),
                const SizedBox(height: 4),
                Text("Date: $scannedAt", style: const TextStyle(fontSize: 16)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Scanned History"),
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
        flexibleSpace: Container(
          decoration: const BoxDecoration(gradient: AppGradients.history),
        ),
      ),
      body:
          loading
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                onRefresh: loadHistory,
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    filterCard(),
                    if (history.isEmpty)
                      const Padding(
                        padding: EdgeInsets.only(top: 40),
                        child: Center(child: Text("No history found")),
                      )
                    else
                      ...history.map((e) => historyItem(e as Map)),
                  ],
                ),
              ),
    );
  }
}

class SetSummaryScreen extends StatefulWidget {
  final Map dealer;
  const SetSummaryScreen({super.key, required this.dealer});

  @override
  State<SetSummaryScreen> createState() => _SetSummaryScreenState();
}

class _SetSummaryScreenState extends State<SetSummaryScreen> {
  bool loading = true;
  List sets = [];

  @override
  void initState() {
    super.initState();
    loadSets();
  }

  Future<void> loadSets() async {
    try {
      final data = await ApiService.getSets(widget.dealer["id"]);
      if (!mounted) return;

      setState(() {
        sets = data["sets"] ?? [];
        loading = false;
      });
    } catch (e) {
      if (!mounted) return;

      setState(() => loading = false);

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Failed to load sets: $e")),
      );
    }
  }

  Future<void> requestRedemption(String setKey) async {
    try {
      final data = await ApiService.requestSetRedemption(
        widget.dealer["id"].toString(),
        setKey,
      );

      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(data["message"] ?? "Request submitted")),
      );

      await loadSets();
    } catch (e) {
      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Request failed: $e")),
      );
    }
  }

  Widget metricPill(String title, String value) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 16),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(22),
        ),
        child: Column(
          children: [
            Text(
              title,
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              value,
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w800,
                fontSize: 18,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget setCard(Map item) {
  final label = (item["part_no"] ?? item["set_name"] ?? item["set_key"] ?? "-").toString();
  final total = int.tryParse("${item["set_size"] ?? item["total"] ?? 10}") ?? 10;
  final scanned = int.tryParse("${item["total_scans"] ?? item["scanned"] ?? 0}") ?? 0;
  final pending = int.tryParse("${item["remaining_scans"] ?? item["pending"] ?? 0}") ?? 0;
  final requestStatus = (item["redemption_status"] ?? "").toString().toLowerCase();

  final bool completed = scanned >= total && pending == 0;
  final bool alreadyRequested =
      requestStatus == "pending" || requestStatus == "approved";

  return Container(
    margin: const EdgeInsets.only(top: 16),
    padding: const EdgeInsets.all(22),
    decoration: BoxDecoration(
      gradient: AppGradients.sets,
      borderRadius: BorderRadius.circular(26),
      boxShadow: [
        BoxShadow(
          color: Colors.black.withValues(alpha: 0.10),
          blurRadius: 14,
          offset: const Offset(0, 6),
        ),
      ],
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          "Set $label",
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: 18,
          ),
        ),
        const SizedBox(height: 18),
        Row(
          children: [
            metricPill("Total", "$total"),
            const SizedBox(width: 12),
            metricPill("Scanned", "$scanned"),
            const SizedBox(width: 12),
            metricPill("Pending", "$pending"),
          ],
        ),
        const SizedBox(height: 18),

        if (alreadyRequested)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 14),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.18),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Text(
              requestStatus == "approved"
                  ? "Redemption Approved"
                  : "Redemption Request Pending",
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w800,
              ),
            ),
          )
        else if (completed)
          SizedBox(
            width: double.infinity,
            height: 48,
            child: ElevatedButton.icon(
              onPressed: () => requestRedemption(label),
              icon: const Icon(Icons.redeem),
              label: const Text("Request Redemption"),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.white,
                foregroundColor: const Color(0xFF7C3AED),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
            ),
          )
        else
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 14),
            decoration: BoxDecoration(
              color: Colors.black.withValues(alpha: 0.16),
              borderRadius: BorderRadius.circular(16),
            ),
            child: const Text(
              "Complete all 10 coupons to request redemption",
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
      ],
    ),
  );
}

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Coupon Sets"),
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
        flexibleSpace: Container(
          decoration: const BoxDecoration(gradient: AppGradients.sets),
        ),
      ),
      body:
          loading
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                onRefresh: loadSets,
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    if (sets.isEmpty)
                      const Padding(
                        padding: EdgeInsets.only(top: 40),
                        child: Center(child: Text("No set data found")),
                      )
                    else
                      ...sets.map((e) => setCard(e as Map)),
                  ],
                ),
              ),
    );
  }
}

class RedemptionHistoryScreen extends StatefulWidget {
  final Map dealer;
  const RedemptionHistoryScreen({super.key, required this.dealer});

  @override
  State<RedemptionHistoryScreen> createState() =>
      _RedemptionHistoryScreenState();
}

class _RedemptionHistoryScreenState extends State<RedemptionHistoryScreen> {
  bool loading = true;
  List redemptions = [];

  @override
  void initState() {
    super.initState();
    loadRedemptions();
  }

  Future<void> loadRedemptions() async {
    try {
      final data = await ApiService.getRedemptionHistory(widget.dealer["id"]);
      if (!mounted) return;
      setState(() {
        redemptions = data["history"] ?? data["redemptions"] ?? [];
        loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => loading = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Failed to load redemption history: $e")),
      );
    }
  }

  Widget redemptionCard(Map item) {
    final redeemedBy =
        (item["redeemed_by"] ?? "-").toString().trim().isEmpty
            ? "-"
            : item["redeemed_by"].toString();

    final redeemedAt =
        (item["redeemed_at"] ?? "").toString().trim().isEmpty
            ? "-"
            : item["redeemed_at"].toString();

    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(22),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.06),
            blurRadius: 14,
            offset: const Offset(0, 5),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            "Redeemed By: $redeemedBy",
            style: const TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: Colors.black87,
            ),
          ),
          const SizedBox(height: 12),
          Text(
            "Part No: ${item["part_no"] ?? "-"}",
            style: const TextStyle(fontSize: 16, color: Colors.black87),
          ),
          const SizedBox(height: 4),
          Text(
            "Product: ${item["product_name"] ?? "-"}",
            style: const TextStyle(fontSize: 16, color: Colors.black87),
          ),
          const SizedBox(height: 4),
          Text(
            "Points: ${item["points"] ?? 0}",
            style: const TextStyle(fontSize: 16, color: Colors.black87),
          ),
          const SizedBox(height: 4),
          Text(
            "Redeemed At: $redeemedAt",
            style: const TextStyle(fontSize: 16, color: Colors.black87),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("Redemption History"),
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
        flexibleSpace: Container(
          decoration: const BoxDecoration(gradient: AppGradients.redemptions),
        ),
      ),
      body:
          loading
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                onRefresh: loadRedemptions,
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children:
                      redemptions.isEmpty
                          ? const [
                            Padding(
                              padding: EdgeInsets.only(top: 40),
                              child: Center(
                                child: Text("No redemption history found"),
                              ),
                            ),
                          ]
                          : redemptions
                              .map((e) => redemptionCard(e as Map))
                              .toList(),
                ),
              ),
    );
  }
}

class AboutUsScreen extends StatelessWidget {
  const AboutUsScreen({super.key});

  Widget infoTile({
    required IconData icon,
    required String title,
    required String subtitle,
    required Color color,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 8,
            offset: const Offset(0, 3),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Icon(icon, color: color, size: 24),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 16,
                  ),
                ),
                const SizedBox(height: 4),
                Text(subtitle, style: const TextStyle(color: Colors.black54)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("About Us"),
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
        flexibleSpace: Container(
          decoration: const BoxDecoration(gradient: AppGradients.teal),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(22),
            decoration: BoxDecoration(
              gradient: AppGradients.teal,
              borderRadius: BorderRadius.circular(24),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.10),
                  blurRadius: 14,
                  offset: const Offset(0, 6),
                ),
              ],
            ),
            child: const Column(
              children: [
                Icon(Icons.business, color: Colors.white, size: 42),
                SizedBox(height: 12),
                Text(
                  "FLOWRA",
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 28,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                SizedBox(height: 8),
                Text(
                  "Coupon scanning, points tracking and dealer rewards made simple.",
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.white70, fontSize: 15),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),
          infoTile(
            icon: Icons.qr_code_scanner,
            title: "Coupon Scanning",
            subtitle: "Dealers can scan or manually enter coupon codes.",
            color: const Color(0xFF2563EB),
          ),
          infoTile(
            icon: Icons.account_balance_wallet,
            title: "Wallet Tracking",
            subtitle:
                "Monitor total points and part-wise rewards in one place.",
            color: const Color(0xFF059669),
          ),
          infoTile(
            icon: Icons.history,
            title: "History & Redemptions",
            subtitle:
                "Review scanned coupons, redemption records and coupon sets.",
            color: const Color(0xFFEA580C),
          ),
        ],
      ),
    );
  }
}

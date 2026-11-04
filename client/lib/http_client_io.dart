import 'package:http/http.dart' as http;

http.Client createHttpClient() => http.Client();

void addCookieHeader(Map<String, String> headers, String cookie) {
  headers['Cookie'] = cookie;
}

import { AdminDashboard } from "@/pages/AdminDashboard";
import { TokenUsagePage } from "@/pages/TokenUsagePage";
import { WebChatPage } from "@/pages/WebChatPage";

function App() {
  // 简单前端路由：根路径是 Web 聊天，/admin 和 /usage 使用同一套登录态。
  const route = window.location.pathname.replace(/\/+$/, "") || "/";
  if (route === "/admin") {
    return <AdminDashboard />;
  }
  if (route === "/usage") {
    return <TokenUsagePage />;
  }
  return <WebChatPage />;
}

export default App;

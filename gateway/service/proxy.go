package service

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"
)

const (
	OpenAIBaseURLEnv = "OPENAI_BASE_URL"
)

func NewLLMProxy(upstreamBaseURL string) (http.Handler, error) {
	upstreamBaseURL = strings.TrimSpace(upstreamBaseURL)
	if upstreamBaseURL == "" {
		return nil, errors.New("missing " + OpenAIBaseURLEnv)
	}

	upstreamURL, err := url.Parse(upstreamBaseURL)
	if err != nil {
		return nil, err
	}

	// http.DefaultTransport 是 Go 默认的 HTTP 传输配置，里面包含连接池、TLS、代理、Keep-Alive 等默认行为。
	// 把接口类型的默认 Transport，断言回它的真实类型 *http.Transport，然后克隆一份，保留全部默认值，避免影响整个进程里其他 HTTP 请求。
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.ResponseHeaderTimeout = 5 * time.Minute

	proxy := &httputil.ReverseProxy{
		Rewrite: func(req *httputil.ProxyRequest) {
			req.SetURL(upstreamURL)

			if _, ok := req.Out.Header["User-Agent"]; !ok {
				req.Out.Header.Set("User-Agent", "")
			}
			// UsageLogger needs the upstream response body to stay inspectable JSON.
			// Some OpenAI clients advertise gzip/br; avoid compressed upstream bodies here.
			req.Out.Header.Set("Accept-Encoding", "identity")
			req.Out.Header.Del("X-User-ID")
		},
		FlushInterval: -1, // 立刻转发
		Transport:     transport,
		ErrorHandler: func(w http.ResponseWriter, _ *http.Request, err error) {
			writeJSONError(w, http.StatusBadGateway, "upstream request failed: "+err.Error())
		},
	}

	return proxy, nil
}

func writeJSONError(w http.ResponseWriter, statusCode int, message string) {
	// 把上游错误统一包装成 JSON
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(statusCode)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error": message,
	})
}

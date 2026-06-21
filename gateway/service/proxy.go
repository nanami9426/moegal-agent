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

	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.ResponseHeaderTimeout = 5 * time.Minute

	proxy := httputil.NewSingleHostReverseProxy(upstreamURL)
	proxy.FlushInterval = -1
	proxy.Transport = transport
	proxy.ErrorHandler = func(w http.ResponseWriter, _ *http.Request, err error) {
		writeJSONError(w, http.StatusBadGateway, "upstream request failed: "+err.Error())
	}

	director := proxy.Director
	proxy.Director = func(req *http.Request) {
		director(req)
		req.Host = upstreamURL.Host

		if _, ok := req.Header["User-Agent"]; !ok {
			req.Header.Set("User-Agent", "")
		}
	}

	return proxy, nil
}

func writeJSONError(w http.ResponseWriter, statusCode int, message string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(statusCode)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error": message,
	})
}

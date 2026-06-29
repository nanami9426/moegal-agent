package tests

import (
	"bytes"
	"compress/gzip"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/nanami9426/moegal-agent/gateway/router"
	"github.com/nanami9426/moegal-agent/gateway/service"
)

func TestRouterForwardsOpenAICompatibleRequest(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method = %s, want %s", r.Method, http.MethodPost)
		}
		if r.URL.Path != "/v1/chat/completions" {
			t.Errorf("path = %s, want /v1/chat/completions", r.URL.Path)
		}
		if r.URL.Query().Get("stream") != "true" {
			t.Errorf("stream query = %q, want true", r.URL.Query().Get("stream"))
		}
		if r.Header.Get("Authorization") != "Bearer test-key" {
			t.Errorf("authorization = %q, want bearer key", r.Header.Get("Authorization"))
		}
		if r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("content-type = %q, want application/json", r.Header.Get("Content-Type"))
		}
		if r.Header.Get("X-Forwarded-For") != "" {
			t.Errorf("x-forwarded-for = %q, want stripped", r.Header.Get("X-Forwarded-For"))
		}
		if r.Header.Get("X-Forwarded-Host") != "" {
			t.Errorf("x-forwarded-host = %q, want stripped", r.Header.Get("X-Forwarded-Host"))
		}
		if r.Header.Get("X-Forwarded-Proto") != "" {
			t.Errorf("x-forwarded-proto = %q, want stripped", r.Header.Get("X-Forwarded-Proto"))
		}

		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}
		if string(body) != `{"model":"test-model","messages":[]}` {
			t.Errorf("body = %s", body)
		}

		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Upstream", "ok")
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer upstream.Close()

	t.Setenv(service.OpenAIBaseURLEnv, upstream.URL+"/v1")

	gateway := httptest.NewServer(router.Router())
	defer gateway.Close()

	req, err := http.NewRequest(
		http.MethodPost,
		gateway.URL+"/v1/chat/completions?stream=true",
		strings.NewReader(`{"model":"test-model","messages":[]}`),
	)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer test-key")
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Forwarded-For", "203.0.113.1")
	req.Header.Set("X-Forwarded-Host", "spoofed.example")
	req.Header.Set("X-Forwarded-Proto", "https")

	response, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()

	responseBody, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusCreated {
		t.Fatalf("status = %d, want %d; body=%s", response.StatusCode, http.StatusCreated, responseBody)
	}
	if response.Header.Get("X-Upstream") != "ok" {
		t.Errorf("x-upstream = %q, want ok", response.Header.Get("X-Upstream"))
	}
	if string(responseBody) != `{"ok":true}` {
		t.Errorf("response body = %s", responseBody)
	}
}

func TestUsageLoggerPrintsTokenUsage(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}
		if string(body) != `{"model":"test-model","user":"legacy-user","messages":[]}` {
			t.Errorf("body = %s", body)
		}
		if r.Header.Get("X-User-ID") != "" {
			t.Errorf("x-user-id = %q, want stripped before upstream", r.Header.Get("X-User-ID"))
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"chatcmpl-test","model":"test-model","choices":[],"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}}`))
	}))
	defer upstream.Close()

	t.Setenv(service.OpenAIBaseURLEnv, upstream.URL+"/v1")

	previousOutput := log.Writer()
	previousFlags := log.Flags()
	var logs bytes.Buffer
	log.SetOutput(&logs)
	log.SetFlags(0)
	defer func() {
		log.SetOutput(previousOutput)
		log.SetFlags(previousFlags)
	}()

	gateway := httptest.NewServer(router.Router())
	defer gateway.Close()

	request, err := http.NewRequest(
		http.MethodPost,
		gateway.URL+"/v1/chat/completions",
		strings.NewReader(`{"model":"test-model","user":"legacy-user","messages":[]}`),
	)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-User-ID", "1000000001")

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()

	_, err = io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}

	logText := logs.String()
	for _, want := range []string{
		"user=1000000001",
		"model=test-model",
		"prompt_tokens=11",
		"completion_tokens=7",
		"total_tokens=18",
	} {
		if !strings.Contains(logText, want) {
			t.Errorf("usage log = %q, want %q", logText, want)
		}
	}
	if strings.Contains(logText, "user=legacy-user") {
		t.Errorf("usage log = %q, must ignore body user", logText)
	}
}

func TestUsageLoggerPrintsTokenUsageWhenClientAcceptsCompression(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		responseBody := []byte(`{"id":"chatcmpl-test","model":"test-model","choices":[],"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}}`)
		if strings.Contains(r.Header.Get("Accept-Encoding"), "gzip") {
			w.Header().Set("Content-Encoding", "gzip")
			gzipWriter := gzip.NewWriter(w)
			_, _ = gzipWriter.Write(responseBody)
			_ = gzipWriter.Close()
			return
		}

		if got := r.Header.Get("Accept-Encoding"); got != "identity" {
			t.Errorf("accept-encoding = %q, want identity", got)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(responseBody)
	}))
	defer upstream.Close()

	t.Setenv(service.OpenAIBaseURLEnv, upstream.URL+"/v1")

	previousOutput := log.Writer()
	previousFlags := log.Flags()
	var logs bytes.Buffer
	log.SetOutput(&logs)
	log.SetFlags(0)
	defer func() {
		log.SetOutput(previousOutput)
		log.SetFlags(previousFlags)
	}()

	gateway := httptest.NewServer(router.Router())
	defer gateway.Close()

	request, err := http.NewRequest(
		http.MethodPost,
		gateway.URL+"/v1/chat/completions",
		strings.NewReader(`{"model":"test-model","messages":[]}`),
	)
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept-Encoding", "gzip, deflate, br")

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()

	_, err = io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}

	logText := logs.String()
	for _, want := range []string{
		"user=unknown",
		"model=test-model",
		"prompt_tokens=11",
		"completion_tokens=7",
		"total_tokens=18",
	} {
		if !strings.Contains(logText, want) {
			t.Errorf("usage log = %q, want %q", logText, want)
		}
	}
}

func TestLLMProxyRequiresUpstreamBaseURL(t *testing.T) {
	_, err := service.NewLLMProxy("")
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), service.OpenAIBaseURLEnv) {
		t.Fatalf("error = %q, want env name", err.Error())
	}
}

func TestRouterReturnsJSONWhenLLMUpstreamIsMissing(t *testing.T) {
	t.Setenv(service.OpenAIBaseURLEnv, "")

	app := router.Router()
	req := httptest.NewRequest(http.MethodGet, "/v1/models", nil)
	recorder := httptest.NewRecorder()

	app.ServeHTTP(recorder, req)

	if recorder.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d; body=%s", recorder.Code, http.StatusInternalServerError, recorder.Body.String())
	}
	if !strings.Contains(recorder.Header().Get("Content-Type"), "application/json") {
		t.Errorf("content-type = %q, want application/json", recorder.Header().Get("Content-Type"))
	}
	if !strings.Contains(recorder.Body.String(), service.OpenAIBaseURLEnv) {
		t.Errorf("body = %s, want missing env name", recorder.Body.String())
	}
}

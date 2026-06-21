package tests

import (
	"io"
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

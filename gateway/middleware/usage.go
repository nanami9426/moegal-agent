package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

type chatCompletionRequest struct {
	Model string `json:"model"`
}

type chatCompletionResponse struct {
	Model string      `json:"model"`
	Usage *tokenUsage `json:"usage"`
}

type tokenUsage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

type usageResponseWriter struct {
	gin.ResponseWriter
	body bytes.Buffer
}

func (w *usageResponseWriter) Write(data []byte) (int, error) {
	w.body.Write(data)
	return w.ResponseWriter.Write(data)
}

func (w *usageResponseWriter) WriteString(data string) (int, error) {
	w.body.WriteString(data)
	return w.ResponseWriter.WriteString(data)
}

// UsageLogger 演示一个最小版 gin middleware：
// 1. 请求进来时先拿到必要信息；
// 2. c.Next() 交给后面的 handler 处理；
// 3. handler 返回后读取响应里的 usage 并打印。
func UsageLogger() gin.HandlerFunc {
	return func(c *gin.Context) {
		if !isChatCompletionRequest(c.Request) {
			c.Next()
			return
		}

		startedAt := time.Now()
		requestInfo := readChatCompletionRequest(c.Request)
		writer := &usageResponseWriter{ResponseWriter: c.Writer}
		c.Writer = writer

		c.Next()

		printTokenUsage(c, requestInfo, writer.body.Bytes(), time.Since(startedAt))
	}
}

func isChatCompletionRequest(r *http.Request) bool {
	return r.Method == http.MethodPost && r.URL.Path == "/v1/chat/completions"
}

func readChatCompletionRequest(r *http.Request) chatCompletionRequest {
	if r.Body == nil {
		return chatCompletionRequest{}
	}

	body, err := io.ReadAll(r.Body)
	// 中间件读过 body 后，必须放回去；否则后面的反向代理就读不到请求内容了。
	// http.Request.Body 是一个一次性流（one-shot stream），io.ReadAll 读完后，流的游标到底，无法 rewind
	r.Body = io.NopCloser(bytes.NewReader(body))
	if err != nil {
		log.Printf("[usage] read request body failed: %v", err)
		return chatCompletionRequest{}
	}

	var requestInfo chatCompletionRequest
	if len(body) > 0 {
		_ = json.Unmarshal(body, &requestInfo)
	}
	return requestInfo
}

func printTokenUsage(c *gin.Context, requestInfo chatCompletionRequest, responseBody []byte, elapsed time.Duration) {
	var response chatCompletionResponse
	if err := json.Unmarshal(responseBody, &response); err != nil || response.Usage == nil {
		log.Printf(
			"[usage] user=%s model=%s status=%d usage=missing elapsed=%s",
			userLabel(c),
			modelLabel(requestInfo.Model, response.Model),
			c.Writer.Status(),
			elapsed.Round(time.Millisecond),
		)
		return
	}

	log.Printf(
		"[usage] user=%s model=%s prompt_tokens=%d completion_tokens=%d total_tokens=%d status=%d elapsed=%s",
		userLabel(c),
		modelLabel(requestInfo.Model, response.Model),
		response.Usage.PromptTokens,
		response.Usage.CompletionTokens,
		response.Usage.TotalTokens,
		c.Writer.Status(),
		elapsed.Round(time.Millisecond),
	)
}

func userLabel(c *gin.Context) string {
	if userID := strings.TrimSpace(c.GetHeader("X-User-ID")); userID != "" {
		return userID
	}
	return "unknown"
}

func modelLabel(requestModel string, responseModel string) string {
	if requestModel != "" {
		return requestModel
	}
	if responseModel != "" {
		return responseModel
	}
	return "unknown"
}

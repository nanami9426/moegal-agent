package middleware

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	_ "github.com/jackc/pgx/v5/stdlib"
)

const databaseURLEnv = "DATABASE_URL"

var (
	usageDBOnce sync.Once
	usageDB     *sql.DB
)

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

// ReverseProxy 可能走 io.ReaderFrom 快路径；这里用 TeeReader 保证响应体仍会被采集。
func (w *usageResponseWriter) ReadFrom(reader io.Reader) (int64, error) {
	tee := io.TeeReader(reader, &w.body)
	if readerFrom, ok := w.ResponseWriter.(io.ReaderFrom); ok {
		return readerFrom.ReadFrom(tee)
	}
	return io.Copy(w.ResponseWriter, tee)
}

// UsageLogger 采集 OpenAI-compatible chat completions 的 token 用量：
// 1. 请求进来时先拿到必要信息；
// 2. c.Next() 交给后面的 handler 处理；
// 3. handler 返回后读取响应里的 usage，并尝试旁路入库。
func UsageLogger() gin.HandlerFunc {
	db := openUsageDB()
	return func(c *gin.Context) {
		if c.Request.Method != http.MethodPost || c.Request.URL.Path != "/v1/chat/completions" {
			c.Next()
			return
		}
		if db == nil {
			c.Next()
			return
		}

		startedAt := time.Now()
		requestModel := readRequestModel(c)

		// 包一层 writer：响应照常返回给客户端，同时留一份 body 用来解析 usage。
		writer := &usageResponseWriter{ResponseWriter: c.Writer}
		c.Writer = writer

		c.Next()

		var response struct {
			Model string          `json:"model"`
			Usage json.RawMessage `json:"usage"`
		}
		if err := json.Unmarshal(writer.body.Bytes(), &response); err != nil || len(response.Usage) == 0 || string(response.Usage) == "null" {
			return
		}

		var usage struct {
			PromptTokens     int `json:"prompt_tokens"`
			CompletionTokens int `json:"completion_tokens"`
			TotalTokens      int `json:"total_tokens"`
		}
		if err := json.Unmarshal(response.Usage, &usage); err != nil {
			log.Printf("[usage] parse usage failed: %v", err)
			return
		}

		userIDText := strings.TrimSpace(c.GetHeader("X-User-ID"))
		if userIDText == "" {
			return
		}
		userID, err := strconv.ParseInt(userIDText, 10, 64)
		if err != nil {
			log.Printf("[usage] invalid X-User-ID=%q: %v", userIDText, err)
			return
		}

		model := requestModel
		if model == "" {
			model = response.Model
		}
		if model == "" {
			model = "unknown"
		}

		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()

		// 用量入库是旁路统计，失败只打日志，不能影响已经完成的模型响应。
		if _, err := db.ExecContext(
			ctx,
			`INSERT INTO llm_token_usages (
				user_id,
				model,
				request_path,
				prompt_tokens,
				completion_tokens,
				total_tokens,
				status_code,
				elapsed_ms,
				raw_usage,
				created_at
			) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
			userID,
			model,
			c.Request.URL.Path,
			usage.PromptTokens,
			usage.CompletionTokens,
			usage.TotalTokens,
			c.Writer.Status(),
			time.Since(startedAt).Milliseconds(),
			string(response.Usage),
			startedAt.UTC(),
		); err != nil {
			log.Printf("[usage] store failed: %v", err)
		}
	}
}

func readRequestModel(c *gin.Context) string {
	if c.Request.Body == nil {
		return ""
	}

	body, err := io.ReadAll(c.Request.Body)
	// 中间件读过 body 后必须放回去；否则后面的反向代理就读不到请求内容了。
	c.Request.Body = io.NopCloser(bytes.NewReader(body))
	if err != nil {
		log.Printf("[usage] read request body failed: %v", err)
		return ""
	}
	if len(body) == 0 {
		return ""
	}

	var request struct {
		Model string `json:"model"`
	}
	_ = json.Unmarshal(body, &request)
	return request.Model
}

func openUsageDB() *sql.DB {
	usageDBOnce.Do(func() {
		databaseURL := normalizeDatabaseURL(os.Getenv(databaseURLEnv))
		if databaseURL == "" {
			return
		}

		db, err := sql.Open("pgx", databaseURL)
		if err != nil {
			log.Printf("[usage] open database failed: %v", err)
			return
		}
		db.SetMaxOpenConns(3)
		db.SetMaxIdleConns(1)
		db.SetConnMaxLifetime(30 * time.Minute)
		usageDB = db
	})
	return usageDB
}

func normalizeDatabaseURL(databaseURL string) string {
	databaseURL = strings.TrimSpace(databaseURL)
	if databaseURL == "" {
		return ""
	}

	// Python 侧使用 SQLAlchemy driver 名，pgx 只需要标准 postgres scheme。
	databaseURL = strings.TrimPrefix(databaseURL, "postgresql+psycopg://")
	if strings.HasPrefix(databaseURL, "postgresql://") {
		return "postgres://" + strings.TrimPrefix(databaseURL, "postgresql://")
	}
	if !strings.HasPrefix(databaseURL, "postgres://") {
		return "postgres://" + databaseURL
	}
	return databaseURL
}

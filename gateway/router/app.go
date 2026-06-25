package router

import (
	"net/http"
	"os"

	"github.com/gin-gonic/gin"
	"github.com/nanami9426/moegal-agent/gateway/middleware"
	"github.com/nanami9426/moegal-agent/gateway/service"
)

func Router() *gin.Engine {
	r := gin.Default()
	r.Use(middleware.UsageLogger())
	r.GET("/healthz", Healthz)
	registerLLMProxyRoutes(r)
	return r
}

func Healthz(c *gin.Context) {
	c.JSON(200, gin.H{
		"status": "ok",
	})
}

func registerLLMProxyRoutes(r *gin.Engine) {
	proxyHandler, err := service.NewLLMProxy(os.Getenv(service.OpenAIBaseURLEnv))
	var handler gin.HandlerFunc
	if err != nil {
		handler = func(c *gin.Context) {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		}
	} else {
		handler = gin.WrapH(http.StripPrefix("/v1", proxyHandler))
	}

	r.Any("/v1", handler)
	r.Any("/v1/*path", handler)
}

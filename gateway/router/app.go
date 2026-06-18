package middlewares

import "github.com/gin-gonic/gin"

func Router() *gin.Engine {
	r := gin.Default()
	r.GET("/healthz", Healthz)
	return r
}

func Healthz(c *gin.Context) {
	c.JSON(200, gin.H{
		"status": "ok",
	})
}
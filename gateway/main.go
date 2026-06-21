package main

import "github.com/nanami9426/moegal-agent/gateway/router"

func main() {
	r := router.Router()
	r.Run(":9426")
}

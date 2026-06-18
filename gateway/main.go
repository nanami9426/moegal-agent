package main

import "github.com/nanami9426/moegal-agent/gateway/router"

func main() {
	r := middlewares.Router()
	r.Run(":9426")
}

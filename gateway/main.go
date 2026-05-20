package main

import "github.com/nanami9426/moegal-agent/gateway/middlewares"

func main() {
	r := middlewares.Router()
	r.Run(":9426")
}

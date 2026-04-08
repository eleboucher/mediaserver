local cache = {}

function enrich(tag, timestamp, record)
    local path = record["container_path"]
    if path then
        local cid = path:match("containers/(%x+)/")
        if cid then
            if not cache[cid] then
                local f = io.open("/var/lib/docker/containers/" .. cid .. "/config.v2.json", "r")
                if f then
                    local data = f:read("*a")
                    f:close()
                    local name = data:match('"Name":"/([^"]+)"')
                    cache[cid] = name or cid:sub(1, 12)
                else
                    cache[cid] = cid:sub(1, 12)
                end
            end
            record["container_name"] = cache[cid]
        end
        record["container_path"] = nil
    end
    record["host"] = "pangolin-vps"
    return 1, timestamp, record
end

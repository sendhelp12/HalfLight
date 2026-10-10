-- Persistent readers avoid reopening high-rate packet files on the game thread.
-- No object APIs run here. Checksum/commit footer reject partial publications.
return function(path,maximum)
    local M={path=path,maximum=maximum}
    local function checksum(text)
        local a,b=1,0
        for i=1,#text do a=(a+text:byte(i))%65521;b=(b+a)%65521 end
        return b*65536+a
    end
    function M:close()
        if self.file then self.file:close();self.file=nil end
    end
    function M:read()
        if not self.file then
            self.file=io.open(self.path:gsub('%.txt$','.stream'),'rb')
            if not self.file then
                local old=io.open(self.path,'rb');if not old then return end
                local text=old:read(self.maximum+1);old:close()
                if text and #text<=self.maximum then return text end
                return
            end
            -- CRT fseek may reuse its old read buffer while another process
            -- updates the same file. Every publication must reach the kernel.
            self.file:setvbuf('no')
        end
        local ok,text=pcall(function()
            assert(self.file:seek('set',0))
            local header=self.file:read(39)
            if not header or #header~=39 then return end
            local sequence,length,sum=header:match('^HLS1,(%d+),(%d+),(%d+)\n$')
            length=tonumber(length);sum=tonumber(sum)
            if not sequence or not length or length<=0 or length>self.maximum then return end
            local payload=self.file:read(length);local footer=self.file:read(22)
            if not payload or #payload~=length or footer~='HLS1,'..sequence..'\n' or checksum(payload)~=sum then return end
            return payload
        end)
        if not ok then self:close();return end
        return text
    end
    return M
end

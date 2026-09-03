curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Authorization: Bearer david_local_7b92a172297ba6fb8bd9ff21bf469610d0bb215a6c4865707aafe310cabc8160' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [
      {
        "role": "user",
        "content": "介绍一下你自己，10个字以内"
      }
    ]
  }'


# david_9667c9c00c9a45e0efb5e6d1217badcd8a780f4a78609d1c
# shawn_20260830_84d56ccc8e665b03ab14676a3e02327c6e21d1da7cfa30191ed00d3fd113b6b9
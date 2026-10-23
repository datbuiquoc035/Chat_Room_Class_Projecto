using System.Text.Json;
using System.Text;
using System.Text.Json.Serialization;
using System.Net;

namespace ChatApp.Frontend.Services;

public class RateLimitException : Exception
{
    public int RetryAfter { get; }
    public RateLimitException(string message, int retryAfter = 60) : base(message)
    {
        RetryAfter = retryAfter;
    }
}

public class ChatService
{
    private readonly HttpClient _httpClient;
    private List<Room>? _cachedRooms;
    private DateTime _lastRoomsFetch = DateTime.MinValue;

    public ChatService(HttpClient httpClient)
    {
        _httpClient = httpClient;
    }

    private void SetUserHeader(string? userId)
    {
        if (!string.IsNullOrEmpty(userId))
        {
            if (_httpClient.DefaultRequestHeaders.Contains("X-User-Id"))
            {
                _httpClient.DefaultRequestHeaders.Remove("X-User-Id");
            }
            _httpClient.DefaultRequestHeaders.Add("X-User-Id", userId);
        }
    }

    public async Task<AuthResponse?> LoginAsync(string username, string password)
    {
        var content = new StringContent(JsonSerializer.Serialize(new { username, password }), Encoding.UTF8, "application/json");
        var response = await _httpClient.PostAsync("/auth/login", content);
        
        if (response.StatusCode == HttpStatusCode.TooManyRequests)
        {
            throw new RateLimitException("Quá giới hạn đăng nhập (HTTP 429 Too Many Requests). Vui lòng thử lại sau!");
        }
        
        if (response.IsSuccessStatusCode)
        {
            var json = await response.Content.ReadAsStringAsync();
            var res = JsonSerializer.Deserialize<AuthResponse>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            if (res != null)
            {
                SetUserHeader(res.User_Id);
            }
            return res;
        }
        
        throw new HttpRequestException("Tài khoản hoặc mật khẩu không chính xác.");
    }

    public async Task<AuthResponse?> RegisterAsync(string username, string password)
    {
        var content = new StringContent(JsonSerializer.Serialize(new { username, password }), Encoding.UTF8, "application/json");
        var response = await _httpClient.PostAsync("/auth/register", content);
        
        if (response.StatusCode == HttpStatusCode.TooManyRequests)
        {
            throw new RateLimitException("Quá giới hạn đăng ký (HTTP 429 Too Many Requests).");
        }

        if (response.IsSuccessStatusCode)
        {
            var json = await response.Content.ReadAsStringAsync();
            var res = JsonSerializer.Deserialize<AuthResponse>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            if (res != null)
            {
                SetUserHeader(res.User_Id);
            }
            return res;
        }
        throw new HttpRequestException("Đăng ký thất bại: Tên tài khoản đã tồn tại hoặc không hợp lệ.");
    }

    public async Task<List<Room>> GetRoomsAsync(string? userId = null, bool forceRefresh = false)
    {
        // Short cache (3 seconds) to prevent duplicate calls on rapid route changes
        if (!forceRefresh && _cachedRooms != null && (DateTime.UtcNow - _lastRoomsFetch).TotalSeconds < 3)
        {
            return _cachedRooms;
        }

        SetUserHeader(userId);
        var response = await _httpClient.GetAsync("/rooms");
        if (response.StatusCode == HttpStatusCode.TooManyRequests)
        {
            throw new RateLimitException("Quá giới hạn gọi danh sách phòng (HTTP 429 Too Many Requests).");
        }
        if (response.IsSuccessStatusCode)
        {
            var json = await response.Content.ReadAsStringAsync();
            var list = JsonSerializer.Deserialize<List<Room>>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? new();
            _cachedRooms = list;
            _lastRoomsFetch = DateTime.UtcNow;
            return list;
        }
        return _cachedRooms ?? new();
    }

    public async Task<Room?> GetRoomAsync(string roomId, string? userId = null)
    {
        SetUserHeader(userId);
        var response = await _httpClient.GetAsync($"/rooms/{roomId}");
        if (response.IsSuccessStatusCode)
        {
            var json = await response.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<Room>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
        }
        return null;
    }

    public async Task<Room?> CreateRoomAsync(string name, string ownerId)
    {
        SetUserHeader(ownerId);
        var content = new StringContent(JsonSerializer.Serialize(new { name, owner_id = ownerId }), Encoding.UTF8, "application/json");
        var response = await _httpClient.PostAsync("/rooms", content);
        if (response.StatusCode == HttpStatusCode.TooManyRequests)
        {
            throw new RateLimitException("Quá giới hạn tạo phòng (HTTP 429 Too Many Requests). Vui lòng chờ 1 phút.");
        }
        if (response.IsSuccessStatusCode)
        {
            _cachedRooms = null; // Invalidate cache
            var json = await response.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<Room>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
        }
        return null;
    }

    public async Task JoinRoomAsync(string roomId, string userId, string username)
    {
        SetUserHeader(userId);
        var content = new StringContent(JsonSerializer.Serialize(new { user_id = userId, username }), Encoding.UTF8, "application/json");
        var response = await _httpClient.PostAsync($"/rooms/{roomId}/join", content);
        if (response.StatusCode == HttpStatusCode.TooManyRequests)
        {
            throw new RateLimitException("Quá giới hạn tham gia phòng (HTTP 429 Too Many Requests).");
        }
    }

    public async Task<List<Message>> GetMessagesAsync(string roomId, string? userId = null)
    {
        SetUserHeader(userId);
        var response = await _httpClient.GetAsync($"/rooms/{roomId}/messages");
        if (response.StatusCode == HttpStatusCode.TooManyRequests)
        {
            throw new RateLimitException("Quá giới hạn tải tin nhắn (HTTP 429 Too Many Requests).");
        }
        if (response.IsSuccessStatusCode)
        {
            var json = await response.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<List<Message>>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? new();
        }
        return new();
    }

    public async Task SendMessageAsync(string roomId, string userId, string username, string contentText)
    {
        SetUserHeader(userId);
        var content = new StringContent(JsonSerializer.Serialize(new { user_id = userId, username, content = contentText }), Encoding.UTF8, "application/json");
        var response = await _httpClient.PostAsync($"/rooms/{roomId}/messages", content);
        if (response.StatusCode == HttpStatusCode.TooManyRequests)
        {
            throw new RateLimitException("Bạn đang gửi tin nhắn quá nhanh! Đã chạm giới hạn 10 requests/phút (HTTP 429 Too Many Requests).");
        }
        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException($"Gửi tin nhắn thất bại: {(int)response.StatusCode}");
        }
    }

    public async Task ResetRateLimitAsync()
    {
        try
        {
            await _httpClient.PostAsync("/ratelimit/reset", null);
        }
        catch { }
    }
}

public class AuthResponse
{
    public string Status { get; set; } = "";
    public string User_Id { get; set; } = "";
    public string Username { get; set; } = "";
}

public class Room
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Owner_Id { get; set; } = "";
    
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public double Created_At { get; set; }

    public int Member_Count { get; set; } = 0;
}

public class Message
{
    public string Id { get; set; } = "";
    public string Room_Id { get; set; } = "";
    public string User_Id { get; set; } = "";
    public string Username { get; set; } = "";
    public string Content { get; set; } = "";
    
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public double Timestamp { get; set; }
}

using System;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

class Program
{
    const int DefaultPort = 9999;
    const int PollMs = 50;

    static readonly int[] VkKeys = { 0x57, 0x41, 0x53, 0x44, 0x5A };
    static readonly char[] KeyChars = { 'w', 'a', 's', 'd', 'z' };
    static readonly bool[] Held = new bool[KeyChars.Length];

    [DllImport("user32.dll")]
    static extern short GetAsyncKeyState(int vKey);

    static bool IsDown(int vk) => (GetAsyncKeyState(vk) & 0x8000) != 0;

    static void SendKey(NetworkStream stream, char key, bool down)
    {
        var msg = Encoding.ASCII.GetBytes($"{(down ? '+' : '-')}{key}");
        stream.Write(msg, 0, msg.Length);
        stream.Flush();
    }

    static void ReleaseAll(NetworkStream stream)
    {
        for (int i = 0; i < KeyChars.Length; i++)
        {
            if (!Held[i])
                continue;
            Held[i] = false;
            SendKey(stream, KeyChars[i], down: false);
        }
    }

    static void PollAndSend(NetworkStream stream)
    {
        for (int i = 0; i < VkKeys.Length; i++)
        {
            bool down = IsDown(VkKeys[i]);
            if (down == Held[i])
                continue;
            Held[i] = down;
            SendKey(stream, KeyChars[i], down);
        }
    }

    static void Main(string[] args)
    {
        string ip = args.Length > 0 ? args[0] : "192.168.149.1";
        int port = args.Length > 1 && int.TryParse(args[1], out int p) ? p : DefaultPort;

        Console.WriteLine("+w/-w, +a/-a, +s/-s, +d/-d, +z/-z");
        Console.WriteLine($"Connecting to {ip}:{port}...");

        try
        {
            using TcpClient client = new TcpClient(ip, port);
            using NetworkStream stream = client.GetStream();

            Console.WriteLine("Connected.");

            while (true)
            {
                if (IsDown(0x1B))
                    break;

                PollAndSend(stream);
                Thread.Sleep(PollMs);
            }

            ReleaseAll(stream);
            Console.WriteLine("Disconnected.");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Eroare: {ex.Message}");
        }
    }
}

using System;
using System.Net.Sockets;
using System.Net;

class Program
{
    private static string ReadString(BinaryReader reader, Action<string> callback = null)
    {
        char term = (char)10;
        char res = '_';
        string str = "";

        while (res != term)
        {
            res = reader.ReadChar();

            if (res != term)
                str += res;

            if (callback != null)
                callback($"{str}: '{(int)res}/{res}'");
        }

        return str;
    }

    private static void WriteString(BinaryWriter writer, string str)
    {
        str = str.Trim();

        foreach (char c in str)
        {
            writer.Write(c);
        }
    }

    private static void ClientReadChars(BinaryWriter writer, BinaryReader reader)
    {
        while (true)
        {
            string str = ReadString(reader);
            Console.WriteLine($"Response: {str}");

            string resp = Console.ReadLine();
            WriteString(writer, resp);
        }
    }

    static void Main(string[] args)
    {
        string ip = "192.168.149.1";

        try
        {
            using (TcpClient client = new TcpClient(ip, 9999))
            using (NetworkStream stream = client.GetStream())
            {
                var writer = new BinaryWriter(stream);
                var reader = new BinaryReader(stream);

                while (true)
                {
                    var input = Console.ReadKey().KeyChar;
                    WriteString(writer, input.ToString());
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Eroare: {ex.Message}");
        }
    }
}
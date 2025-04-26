from openai import OpenAI
from datetime import datetime
from neo4j import GraphDatabase
from datetime import date
import os
from dotenv import load_dotenv
import json
load_dotenv()  # reads .env into os.environ

apiKey = os.getenv("OPENAI_API_KEY")
if not apiKey:
    raise RuntimeError("OPENAI_API_KEY not set")

client = OpenAI(api_key=apiKey)


def rephrase_For_Followup(user_query: str, past_messages: list):

    convo_lines = [
        f"{m['role'].capitalize()}: {m['content']}"
        for m in past_messages[:-1]  # skip duplicate of user_query
    ]
    conversation = "\n".join(convo_lines)

    system_prompt = """
    You are an expert rephrasing assistant. You will rephrase an user query.

    STRICT RULES
    1. Restate the last user message as ONE fully self-contained sentence in **Turkish**.
    2. Replace every pronoun or vague reference (“o”, “bu şirket”, “orası”, etc.) with the correct explicit noun from the conversation (if the information exists).
    3. Preserve the original intent and sentence type (question, command, statement, exclamation).
    4. Do NOT add, infer, or remove facts.
    5. If the user query doesn't need rephrasing, return the original query as is.
    6. Output EXACTLY one sentence—no extra words, no labels, no line breaks.
    """.strip()

    user_prompt = f"""
    Conversation so far:
    {conversation}

    Current user query:
    {user_query}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ],
        temperature=0.1
    )
    return response.choices[0].message.content.strip()


def translateEnglish(text): # will do it tonight
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an expert translator with fluency in English and Turkish languages."},
            {"role": "user", "content": f"Translate the given text from Turkish to English, output only the translated text, nothing else! Also, please do NOT translate the special names in the turkish query(like company names, person names etc.), leave those names in Turkish!. Text: {text} "}
        ],
        temperature=0.12
    )
    return response.choices[0].message.content

def translateTurkish(text): # will do it tonight
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Sen, İngilizce ve Türkçe dillerine akıcı bir şekilde hakim olan uzman bir çevirmenisin."},
            {"role": "user", "content": f"Verilen metni İngilizceden Türkçeye çevir, yalnızca çevrilmiş metni yanıt olarak ver, başka hiçbir şey verme! Metin: {text} "}
        ],
        temperature=0.12
    )
    return response.choices[0].message.content

def relevancy_Check(doc, decomposedQueries, englishUserQuery, isDecomposed): 

    system_prompt = """
    You are an expert analyst that decides whether a document is relevant to at least one
    of the given questions. If the document is even PARTIALLY relevant, reply with
    the single word YES. If it is not relevant at all, reply with the single word NO.
    Reply in uppercase with no punctuation, explanations, or extra words.
    """

    questions_block = "\n".join(f"- {q}" for q in decomposedQueries)

    if isDecomposed:
        questions_block += "\n- " + englishUserQuery
    
    user_prompt = f"""
    DOCUMENT:
    {doc}

    QUESTIONS:
    {questions_block}
    """

    response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.1
    )

    answer = response.choices[0].message.content.strip().upper()
    print(f"DOC: {doc}")
    print(answer)

    return answer.startswith("YES")

def checkSupported(docs, query, answer):
    system_prompt = f"""
    You are an expert fact-checker. If the information(s) in the answer were also stated in the documents, return YES; otherwise, return NO.\n
    Evaluate the answer in the context of the user question and the retrieved documents.\n
    Output **only** YES or NO.
    """
    user_prompt = f"""
    User Question: {query}\n
    Answer: {answer}\n
    Retrieved Documents: {docs}
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
        ],
        temperature=0.12
    )
    answer = response.choices[0].message.content.strip().upper()
    return answer.startswith("YES")


def simpleDecompose(question: str):
    """
    Break a (possibly multi-hop) query into two self-contained sub-questions
    that can help with document retrieval.

    Returns: list[str]  # exactly two questions, or [] on failure
    """
    system_prompt = """
    You are an expert query-decomposition assistant.

    GOAL
    Split the user’s information need into TWO independent, self-contained
    sub-questions that, when answered, together resolve the original query.

    GUIDELINES
    1. Each sub-question must be answerable on its own (no pronouns, no “the company”).
    2. Maintain chronological or logical order if needed.
    3. Output **exactly** the JSON object below—no extra keys, no comments, no text.
    4. Even if the original query is single-hop, return two subquestions which are rephrasings or different aspects of the same question.

    FORMAT 
    {"subquestions": ["Question 1", "Question 2"]}
    """.strip()

    user_prompt = f"""
    Original query:
    {question}

    Decompose it now and output JSON.
    """.strip()

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ],
        temperature=0.1
    )

    raw = response.choices[0].message.content.strip()

    try:
        data = json.loads(raw)
        return data.get("subquestions", [])
    except json.JSONDecodeError as err:
        print("Failed to parse JSON from model:", err, "\nRaw output:", raw)
        return []

def decomposeToSubqueries(question: str):
    return classifyAndDecompose(question)


def classifyAndDecompose(question: str):
    """
    Returns a dict:
      {
        "type": "single" | "bridging" | "intersection" | "comparison" | "composition",
        "subquestions": [q1, q2],
        "bridge_template": "...{answer_to_q1}..."  # only for bridging
      }
    """
    system = """
    You are an expert question analyst. 
    Classify the question as:
    - single            (can be answered in one hop)
    - bridging          (needs an entity/value from Q1 to answer Q2)
    - intersection      (needs entities satisfying multiple constraints)
    - comparison        (needs comparing two entities)
    - composition       (needs aggregating different attributes)
    Then, if not single, produce *TWO* sub-questions that make the reasoning explicit. 
    If type is bridging, put the **second** question as a template containing 
    "{answer_to_q1}" where the answer of the first question should be inserted. 
    Return **ONLY** JSON with keys type, subquestions, bridge_template."

    ### EXAMPLES
    <example>
    Q: What was Akbank’s net profit in 2024?
    A:
    {
    "type": "single",
    "subquestions": ["What was Akbank’s net profit in 2024?"],
    "bridge_template": null
    }
    </example>

    <example>
    Q: Who is the current CEO of the company whose BIST ticker symbol is TCELL?
    A:
    {
    "type": "bridging",
    "subquestions": [
        "Which company has the BIST ticker symbol TCELL?",
        "Who is the current CEO of {answer_to_q1}?"
    ],
    "bridge_template": "Who is the current CEO of {answer_to_q1}?"
    }
    </example>

    <example>
    Q: Which BIST100 companies both produce automotive parts and reported a dividend yield above 5 % in 2024?
    A:
    {
    "type": "intersection",
    "subquestions": [
        "Which BIST100 companies reported a dividend yield above 5 % in 2024?",
        "Which BIST100 companies produce automotive parts?"
    ],
    "bridge_template": null
    }
    </example>

    <example>
    Q: Which had the higher market capitalisation at the end of 2024, Koç Holding or Sabancı Holding?
    A:
    {
    "type": "comparison",
    "subquestions": [
        "What was Koç Holding’s market capitalisation at the end of 2024?",
        "What was Sabancı Holding’s market capitalisation at the end of 2024?"
    ],
    "bridge_template": null
    }
    </example>

    <example>
    Q: Give me the 2024 revenueand net profit margin of Ereğli Demir Çelik.
    A:
    {
    "type": "composition",
    "subquestions": [
        "What was Ereğli Demir Çelik’s revenue in 2024?",
        "What was Ereğli Demir Çelik’s net profit margin in 2024?"
    ],
    "bridge_template": null
    }
    </example>

    <example>
    Q: Which company joined the BIST100 most recently and who is its chairperson?
    A:
    {
    "type": "bridging",
    "subquestions": [
        "Which company most recently joined the BIST100 index?",
        "Who is the chairperson of {answer_to_q1}?"
    ],
    "bridge_template": "Who is the chairperson of {answer_to_q1}?"
    }
    </example>

    <example>
    Q: List all BIST100 firms that both operate in telecommunications and have a free-float ratio above 50 %.
    A:
    {
    "type": "intersection",
    "subquestions": [
        "Which BIST100 firms have a free-float ratio above 50 %?",
        "Which BIST100 firms operate in telecommunications?"
    ],
    "bridge_template": null
    }
    </example>

    <example>
    Q: Compare the EBITDA margins of Aselsan and Turkish Airlines for FY-2024.
    A:
    {
    "type": "comparison",
    "subquestions": [
        "What was Aselsan’s EBITDA margin for FY-2024?",
        "What was Turkish Airlines’ EBITDA margin for FY-2024?"
    ],
    "bridge_template": null
    }
    </example>

    <example> 
    Q: Who is the CEO of the company that raised the largest amount through a Eurobond issuance on Borsa İstanbul in 2024? 
    A: 
    { 
    "type": "bridging", 
    "subquestions": [ 
        "Which company raised the largest amount through a Eurobond issuance on Borsa İstanbul in 2024?", 
        "Who is the CEO of {answer_to_q1}?" 
    ], 
    "bridge_template": "Who is the CEO of {answer_to_q1}?" 
    } 
    </example> 
    
    <example> 
    Q: Which BIST100 constituents both reported a year-over-year increase in gross profit margin and reduced their Scope 1 emissions intensity by at least 10% in FY-2024? 
    A: 
    { 
    "type": "intersection", 
    "subquestions": [ 
        "Which BIST100 constituents reduced their Scope 1 emissions intensity by at least 10% in FY-2024?", 
        "Which BIST100 constituents reported a year-over-year increase in gross profit margin in FY-2024?" 
    ], 
    "bridge_template": null 
    } 
    </example> 

    <example> 
    Q: Provide the 2024 revenue growth and net-debt-to-EBITDA ratio of Koç Holding. 
    A: 
    { 
    "type": "composition", 
    "subquestions": [ 
        "What was Koç Holding’s revenue growth in 2024?", 
        "What was Koç Holding’s net-debt-to-EBITDA ratio in 2024?" 
    ], 
    "bridge_template": null 
    } 
    </example>

    ### END EXAMPLES

    **Note**: In the case of bridging, do not forget to bridge by {answer_to_q1} in the subquestions!
    """
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": question}],
        temperature=0.05
    )

    content = response.choices[0].message.content.strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Fallback: treat as single-hop
        data = {"type": "single", "subquestions": [question], "bridge_template": None}
    return data


def process_single_hop_query(query, current_date):
    user_prompt = f"""You are an AI assistant that extracts companies, dates, and priority ("late", "early", or "none") from user queries to optimize a RAG system. For any user query, analyze and output in one line:
    [Company Search Space List], [Dates], "late"/"early"/"none"
    Guidelines:
    Company Search Space List: List all companies mentioned in the query. If none are mentioned, leave the list empty.
    Dates: Extract any specific dates or date ranges in the format ["Start Date", "End Date"] using "DD.MM.YYYY". Use "-" for unknown or unspecified dates.
    Priority:
    Use "late" if the user seeks the most recent information.
    Use "early" if the user is interested in historical information.
    Use "none" if the query does not imply any time preference.
    Note that if the query's answer must be an up to date answer, use late.
    Examples:
    Example 1:
    User Query:
    "What is the latest financial performance of Tat Gıda?"
    Extraction:
    ["Tat Gıda"], ["-", "-"], "late"
    Example 2:
    User Query:
    "Tell me about the partnership between KOÇ Holding and Sabancı back in 2015."
    Extraction:
    ["KOÇ Holding", "Sabancı"], ["01.01.2015", "31.12.2015"], "early"
    Example 3:
    User Query:
    "Provide the annual reports of Aygaz A.Ş. for the years 2018 to 2020."
    Extraction:
    ["Aygaz A.Ş."], ["01.01.2018", "31.12.2020"], "early"
    Example 4:
    User Query:
    "What's the current status of energy investments in Romania?"
    Extraction:
    [], ["-", "-"], "late"
    Example 5:
    User Query:
    "How did the stock price of Shanghai Electric Power Co Ltd (SEP) change over the last month?"
    Extraction:
    ["Shanghai Electric Power Co Ltd (SEP)"], ["19.10.2023", "19.11.2023"], "late"
    Example 6:
    User Query:
    "Discuss the investment decisions made by YEOTK in August 2024."
    Extraction:
    ["YEOTK"], ["01.08.2024", "31.08.2024"], "early"
    Example 7:
    User Query:
    "Are there any new announcements from the Capital Markets Board?"
    Extraction:
    ["Capital Markets Board"], ["-", "-"], "late"
    Example 8:
    User Query:
    "I'd like information on the dividends distributed by Enerji Yatırımları A.Ş. (EYAŞ) over the past decade."
    Extraction:
    ["Enerji Yatırımları A.Ş. (EYAŞ)"], ["19.11.2013", "19.11.2023"], "early"
    Example 9:
    User Query:
    "What agreements have Tat signed recently?"
    Extraction:
    ["Tat"], ["-", "-"], "late"
    Example 10:
    User Query:
    "Show me the historical shareholding percentages of KOÇ Holding in its subsidiaries."
    Extraction:
    ["KOÇ Holding"], ["-", "-"], "early"
    Example 11:
    User Query:
    "What's the forecast for energy sector investments in 2025?"
    Extraction:
    [], ["01.01.2025", "31.12.2025"], "none"
    Example 12:
    User Query:
    "Explain the details of the contract worth EUR 65.8 million signed by YEOTK and SEP."
    Extraction:
    ["YEOTK", "SEP"], ["-", "-"], "none"
    Example 13:
    User Query:
    "Find information about the capacity increase plans announced by Tat in April 2024."
    Extraction:
    ["Tat"], ["01.04.2024", "30.04.2024"], "early"
    Example 14:
    User Query:
    "Who is the first company that invested in the energy sector?"
    Extraction:
    [], ["-", "-"], "early"
    Example 15:
    User Query:
    "What are the main business sectors of Sabancı Holding?"
    Extraction:
    ["Sabancı Holding"], ["-", "-"], "none"
    Example 16:
    User Query:
    "Provide information on the sustainability initiatives of Tofaş."
    Extraction:
    ["Tofaş"], ["-", "-"], "none"
    Please use these guidelines and examples to extract the [Company Search Space List], [Dates], and "late"/"early"/"none" from any given user query. Ensure that the outputs are presented in one line, as shown in the examples.

    User query: (Note that today is {current_date})
    {query}"""

    system_prompt = """You are an AI assistant that extracts companies, dates, and priority ("late" or "early") from user queries to optimize a RAG system. For any user query, analyze and output in one line:
    [Company Search Space List], [Dates], "late"/"early"/"none" """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.12
    )
    return response.choices[0].message.content





def process_chunk(chunk, current_date, company_name, notificationDate):
    """
    Calls the LLM with the provided prompts and text chunk.

    Args:
        client (OpenAI): OpenAI client instance.
        system_prompt (str): System prompt for the LLM.
        user_prompt (str): User prompt to use with the LLM.
        chunk (str): Text chunk to process.

    Returns:
        str: Response content from the LLM.
    """

    system_prompt = """
    You are a financial information extraction expert that extracts meaningful relationships in the form of (subject-predicate-object-related companies array- date ) for knowledge graph construction. 
    Each fivelet should be descriptive enough so that any one who reads the fivelet should be able to understand the all context. So, specify all the related details into fivelets.
    """

    user_prompt = """
    You are an expert language model specializing in financial text analysis. Your task is to extract "fivelets" from a given text. Each fivelet is a structured representation of information consisting of the following components:
    Entity1: The first entity involved in the relationship.
    Relation: A descriptive action or state capturing a meaningful relationship, avoiding verbs such as "is," "are," "were," or "so."
    Entity2: The second entity involved in the relationship.
    Related Companies: An array of companies related to that specific fivelet (not all companies listed in the text).
    Date Interval: A list containing the start date and end date relevant to the fivelet, formatted as ["Start Date", "End Date"]. If the start or end date is unknown, use "-" in its place.
    Guidelines:
    Descriptive Predicates: Use verbs that convey meaningful actions or states. For example, instead of "X is an engineer," write "X's job is engineering."
    Avoid Comma-Separated Values: Do not include multiple entities or relationships within a single fivelet. If multiple entities or relationships are present, create separate fivelets.
    Include All Relevant Details: Ensure each fivelet is detailed and encompasses all pertinent subjects and specifics.
    Related Companies Array: Always list the companies related to that specific fivelet in the array.
    Extract All Possible Fivelets: Thoroughly extract as many fivelets as possible from the text.
    Date Intervals: Use date intervals to represent the time frame of each fivelet. Be as specific as possible with dates. If only one date is known, place it appropriately and use "-" for the unknown date.
    Self-Contained Fivelets: Each fivelet must be meaningful and understandable on its own without relying on other fivelets for context. Avoid vague references; provide sufficient detail within each fivelet to make it independently clear.
    Process:
    Think Step by Step: Identify all entities, relationships, and relevant dates in the text before extracting fivelets.
    Planning: Outline the key points and events along with their associated dates.
    Extraction: Use your plan to extract fivelets, ensuring each one adheres to the specified format and is self-contained.
    Additional Guidelines:
    Date Intervals: Represent dates as intervals ["Start Date", "End Date"]. Use specific dates when available; otherwise, use "-" to indicate an unknown start or end date.
    Precision in Dates: Be as precise as possible with dates (day, month, year).
    Start and End Dates: The start date signifies when the event or relationship began, and the end date signifies when it ended or was reported.
    Avoid Generic Dates: Do not use broad dates like just the year unless that is all the information provided.
    Include All Information: Ensure all relevant fivelets from the text are extracted, formatted correctly, and are self-contained.
    Examples:
    Text:
    YEOTK's notification on 15.09.2024:
    On 13.08.2024, we announced the partnership agreement we signed with Shanghai Electric Power Co Ltd (SEP) to jointly carry out two separate solar power plant investments under the subsidiaries of DEFIC Globe Enerji A.Ş. (Defic Globe), in which our company holds a 51% stake, in Romania.
    Under the agreement, the investment in the plants with a total capacity of 129 MWp, located in our subsidiaries in Romania, will be made in collaboration with Shanghai Electric Power Co Ltd (SEP), one of China's leading energy groups with an installed capacity of 22,400 MWh as of the end of 2023.
    The turnkey construction of the solar power plants, including engineering services, high voltage transformer substations, and the installation of energy transmission lines, will also be undertaken by our group, and a contract worth EUR 65.8 million has been signed.
    Fivelets:
    ("YEOTK", "announced partnership agreement with", "Shanghai Electric Power Co Ltd (SEP) for joint investments", ["YEOTK", "SEP"], ["13.08.2024", "13.08.2024"])
    ("YEOTK and SEP", "signed partnership agreement", "on 13.08.2024", ["YEOTK", "SEP"], ["13.08.2024", "13.08.2024"])
    ("YEOTK and SEP", "will jointly invest in", "two separate solar power plants in Romania", ["YEOTK", "SEP"], ["13.08.2024", "-"])
    ("DEFIC Globe Enerji A.Ş. (Defic Globe)", "is a subsidiary where YEOTK holds 51% stake", "used for investments", ["YEOTK", "Defic Globe"], ["-", "15.09.2024"])
    ("Investments by YEOTK and SEP", "are under subsidiaries of", "DEFIC Globe Enerji A.Ş. (Defic Globe)", ["YEOTK", "SEP", "Defic Globe"], ["13.08.2024", "-"])
    ("Total capacity of the solar power plants", "is", "129 MWp", ["YEOTK", "SEP"], ["13.08.2024", "-"])
    ("Shanghai Electric Power Co Ltd (SEP)", "is one of China's leading energy groups", "with installed capacity of 22,400 MWh as of end 2023", ["SEP"], ["-", "31.12.2023"])
    ("YEOTK's group", "will undertake", "turnkey construction including engineering services", ["YEOTK"], ["13.08.2024", "-"])
    ("Turnkey construction by YEOTK", "includes", "high voltage transformer substations", ["YEOTK"], ["13.08.2024", "-"])
    ("Turnkey construction by YEOTK", "includes", "installation of energy transmission lines", ["YEOTK"], ["13.08.2024", "-"])
    ("Contract for construction signed by YEOTK and SEP", "is worth", "EUR 65.8 million", ["YEOTK", "SEP"], ["-", "-"])
    ("YEOTK's investments", "are located in", "Romania", ["YEOTK"], ["13.08.2024", "-"])
    ("YEOTK", "announced the partnership agreement", "on 15.09.2024", ["YEOTK"], ["15.09.2024", "15.09.2024"])
    Text:
    KOÇ Holding's notification on 05.11.2024:
    It has been decided by the board of directors of Enerji Yatırımları A.Ş. (EYAŞ), in which our company holds a 77% stake and our subsidiary Aygaz A.Ş. holds a 20% stake, to distribute a cash advance dividend of 7,620,000,000 TL to be paid from EYAŞ's profit for the first nine months of 2024, and to be paid by 31.10.2024.
    The English translation of this announcement is attached. In case of any discrepancies between the versions, the Turkish version shall prevail.
    Fivelets:
    ("KOÇ Holding", "holds 77% stake in", "Enerji Yatırımları A.Ş. (EYAŞ)", ["KOÇ Holding", "EYAŞ"], ["-", "05.11.2024"])
    ("Aygaz A.Ş.", "is a subsidiary of", "KOÇ Holding", ["Aygaz A.Ş.", "KOÇ Holding"], ["-", "05.11.2024"])
    ("Aygaz A.Ş.", "holds 20% stake in", "Enerji Yatırımları A.Ş. (EYAŞ)", ["Aygaz A.Ş.", "EYAŞ"], ["-", "05.11.2024"])
    ("Board of directors of EYAŞ", "decided to distribute", "cash advance dividend of 7,620,000,000 TL", ["EYAŞ"], ["05.11.2024", "05.11.2024"])
    ("Dividend payment from EYAŞ", "will be paid from", "profit for first nine months of 2024", ["EYAŞ"], ["01.01.2024", "30.09.2024"])
    ("Deadline for dividend payment by EYAŞ", "is", "31.10.2024", ["EYAŞ"], ["-", "31.10.2024"])
    ("KOÇ Holding's announcement", "includes", "English translation attached", ["KOÇ Holding"], ["05.11.2024", "05.11.2024"])
    ("Turkish version of the announcement", "prevails over", "English version in case of discrepancies", ["KOÇ Holding"], ["05.11.2024", "05.11.2024"])
    ("EYAŞ", "decided to distribute dividend", "on 05.11.2024", ["EYAŞ"], ["05.11.2024", "05.11.2024"])
    ("Dividend from EYAŞ", "to be paid", "by 31.10.2024", ["EYAŞ"], ["-", "31.10.2024"])
    Text:
    ETYAK's notification on 16.11.2024:
    In accordance with the provision of Article 36, paragraph 2 of the Capital Markets Board's (III-48.5) Communiqué on the Principles Regarding Securities Investment Trusts, titled "Disclosure and Public Information," which states: "In cases where the weighted average price of the partnership's shares on BİAŞ exceeds twice the net asset value per share, it is mandatory to publish the sector-based portfolio and net asset value table on the Public Disclosure Platform (KAP) every business day, starting from the following business day until this situation no longer exists." Accordingly, the sector-based portfolio and total value table dated 17.10.2024 are presented for the information of our shareholders, investors, and the public.
    Fivelets:
    ("ETYAK", "complies with", "Article 36, paragraph 2 of Capital Markets Board's Communiqué", ["ETYAK", "Capital Markets Board"], ["16.11.2024", "16.11.2024"])
    ("Article 36, paragraph 2", "requires", "publication of sector-based portfolio when share price exceeds threshold", ["Capital Markets Board"], ["-", "16.11.2024"])
    ("ETYAK's share price", "exceeded", "twice the net asset value per share", ["ETYAK"], ["-", "16.11.2024"])
    ("ETYAK", "published", "sector-based portfolio dated 17.10.2024", ["ETYAK"], ["17.10.2024", "17.10.2024"])
    ("ETYAK", "published", "net asset value table dated 17.10.2024", ["ETYAK"], ["17.10.2024", "17.10.2024"])
    ("Sector-based portfolio and net asset value table", "are presented for", "shareholders", ["ETYAK"], ["17.10.2024", "-"])
    ("Sector-based portfolio and net asset value table", "are presented for", "investors", ["ETYAK"], ["17.10.2024", "-"])
    ("Sector-based portfolio and net asset value table", "are presented for", "the public", ["ETYAK"], ["17.10.2024", "-"])
    ("Requirement to publish daily", "starts from", "the following business day after share price exceeds threshold", ["Capital Markets Board"], ["-", "16.11.2024"])
    ("Publication requirement", "continues until", "the situation no longer exists", ["Capital Markets Board"], ["-", "16.11.2024"])
    ("Article 36, paragraph 2", "is part of", "Communiqué on the Principles Regarding Securities Investment Trusts", ["Capital Markets Board"], ["-", "16.11.2024"])
    ("Communiqué III-48.5", "is titled", "Disclosure and Public Information", ["Capital Markets Board"], ["-", "16.11.2024"])
    Text:
    Tat's notification on 30.09.2024:
    In relation to the investment decision in the sauces and ready-made meals categories, with an investment cost of approximately 10 million Euros, as announced in our special circumstance disclosures dated 18.04.2024, for the additional capacity increase plan of 40 million units/year in the sauces category; our current production capacity of plastic bottle sauces (ketchup/mayonnaise and other seasoning sauces), which was 70 million units/year, has been increased by 10 million units/year, reaching a total capacity of 85 million units/year. The cost of the investment expenditures made for machinery equipment, construction, infrastructure, and storage areas amounts to 2.6 million Euros. Also, we have signed an agreement with KOÇ Holding and Sabancı and got their investments.
    Fivelets:
    ("Tat", "announced investment decision in", "sauces and ready-made meals categories costing approximately 10 million Euros", ["Tat"], ["18.04.2024", "18.04.2024"])
    ("Tat", "plans additional capacity increase of", "40 million units/year in sauces category", ["Tat"], ["18.04.2024", "-"])
    ("Tat's production capacity of plastic bottle sauces", "was", "70 million units/year before increase", ["Tat"], ["-", "30.09.2024"])
    ("Tat", "increased production capacity by", "10 million units/year", ["Tat"], ["30.09.2024", "30.09.2024"])
    ("Tat's total production capacity", "reached", "85 million units/year", ["Tat"], ["30.09.2024", "-"])
    ("Investment expenditures by Tat", "amount to", "2.6 million Euros for machinery, construction, infrastructure, and storage", ["Tat"], ["30.09.2024", "30.09.2024"])
    ("Tat", "signed agreement with", "KOÇ Holding for investment", ["Tat", "KOÇ Holding"], ["-", "30.09.2024"])
    ("Tat", "signed agreement with", "Sabancı for investment", ["Tat", "Sabancı"], ["-", "30.09.2024"])
    ("Tat", "received investments from", "KOÇ Holding and Sabancı", ["Tat", "KOÇ Holding", "Sabancı"], ["-", "30.09.2024"])
    ("Tat's capacity increase", "includes", "plastic bottle sauces like ketchup, mayonnaise, and other seasoning sauces", ["Tat"], ["30.09.2024", "-"])
    ("Special circumstance disclosures by Tat", "were dated", "18.04.2024", ["Tat"], ["18.04.2024", "18.04.2024"])
    Please use these guidelines and examples to extract fivelets from any given text, ensuring clarity, accuracy, completeness, and that each fivelet is self-contained and meaningful on its own.

    Text:
    """
    user_prompt += f"{company_name}'s Notification on {notificationDate}, todays date is: {current_date}"
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt + "\n\n" + chunk}
        ],
        temperature=0.12
    )
    return response.choices[0].message.content



def generate_answer(documents, user_question):

    today_date = datetime.now()
    formatted_date = today_date.strftime("%d-%m-%Y")

    system_prompt = (
        "You are an AI assistant specialized in financial information. You are provided with several financial documents from various companies. "
        "Use only the information contained in these documents to answer the user's query. "
        "If the answer is not present in the relevant documents, respond by saying, \"I don't know.\""
        "But also, if you are said to comment on something, please make comments if related information available in the documents."
    )

    prompt = (
        "You are an AI assistant specialized in financial information. You will be provided with several financial documents from various companies, each starting with the date of notification and the company name. "
        "Use only the information contained in the documents to answer the user's query.\n\n"
        f"Today's date is {formatted_date} \n"
        "Instructions:\n"
        "- Try to be helpful"
        "- If the answer is not present in the relevant documents, respond by saying, \"I don't know.\"\n\n"
        "However, if you are said to comment on something, try to be helpful and make comments by using the documents provided, iff they are related with the question in some sense."
        "Documents:\n"
    )

    """        "- Determine if the user's question specifies a company name.\n"
        "- If a company name is specified, use only the documents related to that company to answer the question.\n"
        "- If no company name is specified, consider all documents.\n" """
    
    # Append each document to the prompt
    for idx, doc in enumerate(documents, 1):
        prompt += f"Document {idx}: {doc}\n\n"
    
    # Add the user's question to the prompt
    prompt += f"User's Question:\n{user_question}\n\nYour Answer:"
    
    # Call the OpenAI API to get the assistant's response
    response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            temperature=0.12
    )
    
    # Extract and return the assistant's answer
    return response.choices[0].message.content

    



